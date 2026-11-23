"""Monitoring pipeline.

claim due endpoints -> HTTP check (+ TLS probe) -> anomaly score -> state machine -> alerts
-> commit -> webhooks -> live events on the WebSocket bus.

Alerting is *state based* rather than event based: "the endpoint is DOWN and has no open DOWN
alert" creates one; "the endpoint is not DOWN but has an open DOWN alert" resolves it and emits
RECOVERED. That stays correct across maintenance windows, restarts and races.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import as_utc, utcnow
from app.core.config import Settings
from app.core.logging import log_extra
from app.domain import AlertKind, AlertSeverity, EndpointStatus
from app.models import Alert, CheckResult, Endpoint
from app.observability.metrics import ALERTS_TOTAL, observe_check
from app.schemas.alert import AlertRead
from app.schemas.check import CheckResultRead
from app.services.anomaly import NOT_EVALUATED, AnomalyResult, detect_latency_anomaly
from app.services.checker import CheckOutcome, CheckSpec, HealthChecker
from app.services.events import EventBus
from app.services.notifier import AlertEvent, Notifier
from app.services.ssl_check import SslInfo, SslProbe, fetch_certificate_expiry
from app.services.state import evaluate_transition

logger = logging.getLogger(__name__)

SSL_ALERT_COOLDOWN = timedelta(hours=24)


class MonitorService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        checker: HealthChecker,
        notifier: Notifier,
        settings: Settings,
        *,
        events: EventBus | None = None,
        ssl_probe: SslProbe | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._checker = checker
        self._notifier = notifier
        self._settings = settings
        self._events = events or EventBus()
        self._ssl_probe = ssl_probe or fetch_certificate_expiry

    # ------------------------------------------------------------------ scheduling

    async def claim_due_endpoints(self, limit: int, *, now: datetime | None = None) -> list[CheckSpec]:
        """Atomically lease due endpoints by pushing their next_check_at forward.

        `FOR UPDATE SKIP LOCKED` lets several Sentinel replicas share one database without
        ever checking the same endpoint twice in the same interval (no leader election needed).
        """
        now = now or utcnow()
        async with self._sessionmaker() as session:
            stmt = (
                select(Endpoint)
                .where(Endpoint.is_active.is_(True), Endpoint.next_check_at <= now)
                .order_by(Endpoint.next_check_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            endpoints = (await session.scalars(stmt)).all()
            specs = []
            for endpoint in endpoints:
                endpoint.next_check_at = now + timedelta(seconds=endpoint.interval_seconds)
                specs.append(CheckSpec.from_endpoint(endpoint))
            await session.commit()
        return specs

    async def run_now(self, endpoint_id: int) -> CheckResultRead | None:
        """On-demand check (API-triggered). Returns None if the endpoint does not exist."""
        async with self._sessionmaker() as session:
            endpoint = await session.get(Endpoint, endpoint_id)
            if endpoint is None:
                return None
            spec = CheckSpec.from_endpoint(endpoint)
        return await self.execute(spec)

    async def execute(self, spec: CheckSpec) -> CheckResultRead | None:
        # Network I/O happens with no DB connection held, so slow endpoints never starve the pool.
        outcome = await self._checker.run(spec)
        ssl_info = await self._maybe_probe_ssl(spec)
        return await self.record(spec, outcome, ssl_info=ssl_info)

    async def _maybe_probe_ssl(self, spec: CheckSpec) -> SslInfo | None:
        if not self._settings.ssl_checks_enabled:
            return None
        parts = urlsplit(spec.url)
        if parts.scheme != "https" or not parts.hostname:
            return None
        now = utcnow()
        interval = timedelta(hours=self._settings.ssl_check_interval_hours)
        if spec.ssl_checked_at is not None and now - as_utc(spec.ssl_checked_at) < interval:
            return None
        try:
            expires_at = await self._ssl_probe(parts.hostname, parts.port or 443)
        except Exception as exc:
            return SslInfo(checked_at=now, expires_at=None, error=f"{type(exc).__name__}: {exc}"[:300])
        return SslInfo(checked_at=now, expires_at=expires_at)

    # ------------------------------------------------------------------ persistence

    async def record(
        self, spec: CheckSpec, outcome: CheckOutcome, *, ssl_info: SslInfo | None = None
    ) -> CheckResultRead | None:
        async with self._sessionmaker() as session:
            # Row lock serialises concurrent results for the same endpoint (scheduler + manual run).
            endpoint = await session.get(Endpoint, spec.endpoint_id, with_for_update=True)
            if endpoint is None:
                logger.info("endpoint deleted during check", extra=log_extra(endpoint_id=spec.endpoint_id))
                return None

            in_maintenance = (
                endpoint.maintenance_until is not None
                and as_utc(endpoint.maintenance_until) > outcome.checked_at
            )
            anomaly = await self._evaluate_anomaly(session, endpoint.id, outcome)
            result = CheckResult(
                endpoint_id=endpoint.id,
                checked_at=outcome.checked_at,
                status_code=outcome.status_code,
                response_time_ms=outcome.response_time_ms,
                is_success=outcome.is_success,
                error_type=outcome.error_type.value if outcome.error_type else None,
                error_message=outcome.error_message,
                attempts=outcome.attempts,
                is_anomaly=anomaly.is_anomaly,
                anomaly_score=anomaly.score,
                in_maintenance=in_maintenance,
            )
            session.add(result)

            previous = endpoint.current_status
            transition = evaluate_transition(
                previous=previous,
                consecutive_failures=endpoint.consecutive_failures,
                is_success=outcome.is_success,
                is_degraded=outcome.is_degraded,
                failure_threshold=self._settings.alert_failure_threshold,
            )
            endpoint.current_status = transition.status
            endpoint.consecutive_failures = transition.consecutive_failures
            endpoint.last_checked_at = outcome.checked_at

            alerts: list[Alert] = []
            open_down = await self._open_alert(session, endpoint.id, AlertKind.DOWN)
            if transition.status == EndpointStatus.DOWN:
                if open_down is None and not in_maintenance:
                    alerts.append(self._down_alert(endpoint, outcome, transition.consecutive_failures))
            elif open_down is not None:
                open_down.resolved_at = outcome.checked_at
                alerts.append(self._recovered_alert(endpoint, outcome, open_down))

            # Latency back to normal -> close any open anomaly alert (they must not pile up).
            if outcome.is_success and outcome.response_time_ms is not None and not anomaly.is_anomaly:
                await session.execute(
                    update(Alert)
                    .where(
                        Alert.endpoint_id == endpoint.id,
                        Alert.kind == AlertKind.LATENCY_ANOMALY,
                        Alert.resolved_at.is_(None),
                    )
                    .values(resolved_at=outcome.checked_at)
                )

            if (
                anomaly.is_anomaly
                and not in_maintenance
                and not await self._alerted_since(
                    session,
                    endpoint.id,
                    AlertKind.LATENCY_ANOMALY,
                    outcome.checked_at - timedelta(seconds=self._settings.alert_cooldown_seconds),
                )
            ):
                alerts.append(self._anomaly_alert(endpoint, outcome, anomaly))

            if ssl_info is not None:
                endpoint.ssl_checked_at = ssl_info.checked_at
                endpoint.ssl_error = ssl_info.error
                if ssl_info.expires_at is not None:
                    endpoint.ssl_expires_at = ssl_info.expires_at
                    ssl_alert = await self._maybe_ssl_alert(session, endpoint, ssl_info, in_maintenance)
                    if ssl_alert is not None:
                        alerts.append(ssl_alert)

            session.add_all(alerts)
            await session.commit()
            read = CheckResultRead.model_validate(result)

            # Deliver after commit: a slow webhook never holds a transaction open.
            for alert in alerts:
                alert.notified = await self._notifier.notify(
                    AlertEvent(
                        alert_id=alert.id,
                        kind=alert.kind,
                        severity=alert.severity,
                        endpoint_id=endpoint.id,
                        endpoint_name=endpoint.name,
                        endpoint_url=endpoint.url,
                        message=alert.message,
                        created_at=alert.created_at,
                        recipients=tuple(endpoint.alert_emails or ()),
                    )
                )
                ALERTS_TOTAL.labels(kind=alert.kind.value).inc()
            if alerts:
                await session.commit()

            endpoint_name = endpoint.name
            alert_payloads = [
                {**AlertRead.model_validate(a).model_dump(mode="json"), "endpoint_name": endpoint_name}
                for a in alerts
            ]

        observe_check(
            endpoint_name,
            is_success=outcome.is_success,
            is_degraded=outcome.is_degraded,
            latency_ms=outcome.response_time_ms,
            status=transition.status,
            is_anomaly=anomaly.is_anomaly,
        )
        self._events.publish(
            "check",
            {
                "endpoint_id": spec.endpoint_id,
                "endpoint_name": endpoint_name,
                "status": transition.status.value,
                "consecutive_failures": transition.consecutive_failures,
                "result": read.model_dump(mode="json"),
            },
        )
        if previous != transition.status:
            self._events.publish(
                "status_changed",
                {
                    "endpoint_id": spec.endpoint_id,
                    "endpoint_name": endpoint_name,
                    "previous": previous.value,
                    "current": transition.status.value,
                },
            )
            logger.warning(
                "endpoint status changed",
                extra=log_extra(
                    endpoint=endpoint_name, previous=previous.value, current=transition.status.value
                ),
            )
        for payload in alert_payloads:
            self._events.publish("alert", payload)
        return read

    async def purge_old_results(self, *, now: datetime | None = None) -> int:
        cutoff = (now or utcnow()) - timedelta(days=self._settings.retention_days)
        async with self._sessionmaker() as session:
            result = await session.execute(delete(CheckResult).where(CheckResult.checked_at < cutoff))
            await session.commit()
        return result.rowcount or 0

    # ------------------------------------------------------------------ helpers

    async def _evaluate_anomaly(
        self, session: AsyncSession, endpoint_id: int, outcome: CheckOutcome
    ) -> AnomalyResult:
        if not outcome.is_success or outcome.response_time_ms is None:
            return NOT_EVALUATED
        stmt = (
            select(CheckResult.response_time_ms)
            .where(
                CheckResult.endpoint_id == endpoint_id,
                CheckResult.is_success.is_(True),
                CheckResult.response_time_ms.is_not(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(self._settings.anomaly_window)
        )
        history = (await session.scalars(stmt)).all()
        return detect_latency_anomaly(
            history,
            outcome.response_time_ms,
            threshold=self._settings.anomaly_threshold,
            min_samples=self._settings.anomaly_min_samples,
            min_delta_ms=self._settings.anomaly_min_delta_ms,
            min_ratio=self._settings.anomaly_min_ratio,
        )

    @staticmethod
    async def _open_alert(session: AsyncSession, endpoint_id: int, kind: AlertKind) -> Alert | None:
        stmt = (
            select(Alert)
            .where(Alert.endpoint_id == endpoint_id, Alert.kind == kind, Alert.resolved_at.is_(None))
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        return await session.scalar(stmt)

    @staticmethod
    async def _alerted_since(
        session: AsyncSession, endpoint_id: int, kind: AlertKind, since: datetime
    ) -> bool:
        stmt = (
            select(Alert.id)
            .where(Alert.endpoint_id == endpoint_id, Alert.kind == kind, Alert.created_at >= since)
            .limit(1)
        )
        return (await session.scalar(stmt)) is not None

    async def _maybe_ssl_alert(
        self, session: AsyncSession, endpoint: Endpoint, ssl_info: SslInfo, in_maintenance: bool
    ) -> Alert | None:
        assert ssl_info.expires_at is not None
        days_left = (as_utc(ssl_info.expires_at) - ssl_info.checked_at).total_seconds() / 86400
        if days_left > self._settings.ssl_warning_days or in_maintenance:
            return None
        if await self._alerted_since(
            session, endpoint.id, AlertKind.SSL_EXPIRING, ssl_info.checked_at - SSL_ALERT_COOLDOWN
        ):
            return None
        expiry = as_utc(ssl_info.expires_at).strftime("%Y-%m-%d")
        if days_left <= 0:
            severity = AlertSeverity.CRITICAL
            message = f"{endpoint.name} TLS certificate EXPIRED on {expiry}"
        else:
            severity = AlertSeverity.WARNING
            message = f"{endpoint.name} TLS certificate expires in {int(days_left)} days ({expiry})"
        return Alert(
            endpoint_id=endpoint.id,
            kind=AlertKind.SSL_EXPIRING,
            severity=severity,
            message=message,
            created_at=ssl_info.checked_at,
            notified=False,
        )

    @staticmethod
    def _down_alert(endpoint: Endpoint, outcome: CheckOutcome, failures: int) -> Alert:
        detail = outcome.error_message or (outcome.error_type.value if outcome.error_type else "failed")
        return Alert(
            endpoint_id=endpoint.id,
            kind=AlertKind.DOWN,
            severity=AlertSeverity.CRITICAL,
            message=f"{endpoint.name} is DOWN after {failures} consecutive failed checks: {detail}",
            created_at=outcome.checked_at,
            notified=False,
        )

    @staticmethod
    def _recovered_alert(endpoint: Endpoint, outcome: CheckOutcome, down_alert: Alert) -> Alert:
        latency = f"{outcome.response_time_ms:.0f} ms" if outcome.response_time_ms is not None else "n/a"
        downtime = (outcome.checked_at - as_utc(down_alert.created_at)).total_seconds()
        return Alert(
            endpoint_id=endpoint.id,
            kind=AlertKind.RECOVERED,
            severity=AlertSeverity.INFO,
            message=(
                f"{endpoint.name} has RECOVERED after {_human_duration(downtime)} "
                f"(HTTP {outcome.status_code}, {latency})"
            ),
            created_at=outcome.checked_at,
            resolved_at=outcome.checked_at,
            notified=False,
        )

    @staticmethod
    def _anomaly_alert(endpoint: Endpoint, outcome: CheckOutcome, anomaly: AnomalyResult) -> Alert:
        message = (
            f"{endpoint.name} latency anomaly: {outcome.response_time_ms:.0f} ms vs baseline "
            f"median {anomaly.baseline_median_ms:.0f} ms (robust z-score {anomaly.score:.1f})"
        )
        return Alert(
            endpoint_id=endpoint.id,
            kind=AlertKind.LATENCY_ANOMALY,
            severity=AlertSeverity.WARNING,
            message=message,
            created_at=outcome.checked_at,
            notified=False,
        )


def _human_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"
