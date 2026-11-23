"""Public status page model (like status.github.com)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import as_utc, utcnow
from app.domain import AlertKind, EndpointStatus
from app.models import Alert, Endpoint
from app.schemas.analytics import StatusIncident, StatusPage, StatusService
from app.services.analytics import daily_uptime

STATUS_DAYS = 90


def _service_status(endpoint: Endpoint) -> str:
    now = utcnow()
    if endpoint.maintenance_until is not None and as_utc(endpoint.maintenance_until) > now:
        return "maintenance"
    return endpoint.current_status.value


def _overall(statuses: list[str]) -> str:
    if not statuses:
        return "operational"
    down = statuses.count(EndpointStatus.DOWN.value)
    if down and down == len(statuses):
        return "major_outage"
    if down:
        return "partial_outage"
    if EndpointStatus.DEGRADED.value in statuses:
        return "degraded"
    if "maintenance" in statuses:
        return "maintenance"
    return "operational"


async def build_status_page(session: AsyncSession) -> StatusPage:
    endpoints = (
        await session.scalars(
            select(Endpoint)
            .where(Endpoint.is_public.is_(True), Endpoint.is_active.is_(True))
            .order_by(Endpoint.name)
        )
    ).all()
    uptime = await daily_uptime(session, days=STATUS_DAYS, public_only=True)

    services = []
    for endpoint in endpoints:
        days = uptime.get(endpoint.id, [])
        total = sum(d.total_checks for d in days)
        ok = sum(d.total_checks * (d.uptime_pct or 0) / 100 for d in days)
        services.append(
            StatusService(
                id=endpoint.id,
                name=endpoint.name,
                status=_service_status(endpoint),
                uptime_pct=round(100 * ok / total, 3) if total else None,
                days=days,
            )
        )

    public_ids = [e.id for e in endpoints]
    names = {e.id: e.name for e in endpoints}
    incidents: list[StatusIncident] = []
    if public_ids:
        alerts = (
            await session.scalars(
                select(Alert)
                .where(
                    Alert.endpoint_id.in_(public_ids),
                    Alert.kind == AlertKind.DOWN,
                    Alert.created_at >= utcnow() - timedelta(days=14),
                )
                .order_by(Alert.created_at.desc())
                .limit(10)
            )
        ).all()
        incidents = [
            StatusIncident(
                service=names[a.endpoint_id],
                message=a.message,
                started_at=a.created_at,
                resolved_at=a.resolved_at,
            )
            for a in alerts
        ]

    return StatusPage(
        overall=_overall([s.status for s in services]),
        generated_at=utcnow(),
        services=services,
        incidents=incidents,
    )
