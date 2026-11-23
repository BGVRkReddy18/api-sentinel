"""Reliability analytics written in raw SQL (PostgreSQL).

Percentiles, FILTER clauses, date_trunc bucketing and a gaps-and-islands window query run inside
the database, so the API never pulls raw time-series rows into Python.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import Boolean, DateTime, Integer, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CheckResult
from app.schemas.analytics import (
    DailyUptime,
    EndpointRecentChecks,
    EndpointSummary,
    ErrorBreakdown,
    Incident,
    RecentCheck,
    TimeseriesPoint,
)

Bucket = Literal["minute", "hour", "day"]


class AnalyticsUnavailableError(RuntimeError):
    """Raised when a PostgreSQL-only query runs against another database (e.g. SQLite in tests)."""


def _require_postgres(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql":
        raise AnalyticsUnavailableError("percentile analytics require PostgreSQL")


_SUMMARY_SQL = """
SELECT
    e.id                                                   AS endpoint_id,
    e.name                                                 AS name,
    e.current_status                                       AS current_status,
    COUNT(r.id)                                            AS total_checks,
    COUNT(r.id) FILTER (WHERE NOT r.is_success)            AS failed_checks,
    ROUND(100.0 * COUNT(r.id) FILTER (WHERE r.is_success)
          / NULLIF(COUNT(r.id), 0), 3)                     AS uptime_pct,
    AVG(r.response_time_ms) FILTER (WHERE r.is_success)    AS avg_latency_ms,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY r.response_time_ms)
        FILTER (WHERE r.is_success)                        AS p50_latency_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY r.response_time_ms)
        FILTER (WHERE r.is_success)                        AS p95_latency_ms,
    percentile_cont(0.99) WITHIN GROUP (ORDER BY r.response_time_ms)
        FILTER (WHERE r.is_success)                        AS p99_latency_ms,
    COUNT(r.id) FILTER (WHERE r.is_anomaly)                AS anomalies
FROM endpoints e
LEFT JOIN check_results r
       ON r.endpoint_id = e.id
      AND r.checked_at >= :since
      AND NOT r.in_maintenance          -- planned downtime does not count against the SLA
{where}
GROUP BY e.id
ORDER BY e.id
"""


async def endpoint_summary(
    session: AsyncSession, *, since: datetime, endpoint_id: int | None = None
) -> list[EndpointSummary]:
    _require_postgres(session)
    where = "WHERE e.id = :endpoint_id" if endpoint_id is not None else ""
    stmt = text(_SUMMARY_SQL.format(where=where)).bindparams(
        bindparam("since", type_=DateTime(timezone=True))
    )
    params: dict = {"since": since}
    if endpoint_id is not None:
        params["endpoint_id"] = endpoint_id
    rows = (await session.execute(stmt, params)).mappings().all()
    return [
        EndpointSummary(
            **{**row, "uptime_pct": float(row["uptime_pct"]) if row["uptime_pct"] is not None else None}
        )
        for row in rows
    ]


_TIMESERIES_SQL = """
SELECT
    date_trunc(:bucket, r.checked_at)                     AS bucket,
    COUNT(*)                                              AS total_checks,
    COUNT(*) FILTER (WHERE r.is_success)                  AS successful_checks,
    AVG(r.response_time_ms) FILTER (WHERE r.is_success)   AS avg_latency_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY r.response_time_ms)
        FILTER (WHERE r.is_success)                       AS p95_latency_ms
FROM check_results r
WHERE r.endpoint_id = :endpoint_id
  AND r.checked_at >= :since
GROUP BY 1
ORDER BY 1
"""


async def latency_timeseries(
    session: AsyncSession, *, endpoint_id: int, since: datetime, bucket: Bucket
) -> list[TimeseriesPoint]:
    _require_postgres(session)
    stmt = text(_TIMESERIES_SQL).bindparams(bindparam("since", type_=DateTime(timezone=True)))
    rows = await session.execute(stmt, {"bucket": bucket, "endpoint_id": endpoint_id, "since": since})
    return [TimeseriesPoint(**row) for row in rows.mappings().all()]


async def error_breakdown(
    session: AsyncSession, *, endpoint_id: int, since: datetime
) -> list[ErrorBreakdown]:
    """Portable (ORM-built) aggregate: which failure modes dominate."""
    count = func.count(CheckResult.id).label("count")
    stmt = (
        select(
            CheckResult.error_type.label("error_type"),
            count,
            func.max(CheckResult.checked_at).label("last_seen"),
        )
        .where(
            CheckResult.endpoint_id == endpoint_id,
            CheckResult.checked_at >= since,
            CheckResult.error_type.is_not(None),
        )
        .group_by(CheckResult.error_type)
        .order_by(count.desc())
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [ErrorBreakdown(**row) for row in rows]


# Gaps-and-islands: consecutive failures share the same (global row number - per-outcome row
# number), so GROUP BY that difference collapses each failure streak into one incident.
_INCIDENTS_SQL = """
WITH ordered AS (
    SELECT
        checked_at,
        is_success,
        ROW_NUMBER() OVER (ORDER BY checked_at, id)
          - ROW_NUMBER() OVER (PARTITION BY is_success ORDER BY checked_at, id) AS grp
    FROM check_results
    WHERE endpoint_id = :endpoint_id
      AND checked_at >= :since
),
latest AS (
    SELECT MAX(checked_at) AS latest_at FROM ordered
)
SELECT
    MIN(o.checked_at)                                   AS started_at,
    MAX(o.checked_at)                                   AS last_failure_at,
    COUNT(*)                                            AS failed_checks,
    MAX(o.checked_at) = (SELECT latest_at FROM latest)  AS ongoing
FROM ordered o
WHERE NOT o.is_success
GROUP BY o.grp
ORDER BY started_at DESC
LIMIT :limit
"""


async def incidents(
    session: AsyncSession, *, endpoint_id: int, since: datetime, limit: int = 50
) -> list[Incident]:
    stmt = (
        text(_INCIDENTS_SQL)
        .bindparams(bindparam("since", type_=DateTime(timezone=True)))
        .columns(
            started_at=DateTime(timezone=True),
            last_failure_at=DateTime(timezone=True),
            failed_checks=Integer,
            ongoing=Boolean,
        )
    )
    rows = await session.execute(stmt, {"endpoint_id": endpoint_id, "since": since, "limit": limit})
    return [
        Incident(
            started_at=row.started_at,
            last_failure_at=row.last_failure_at,
            failed_checks=row.failed_checks,
            duration_seconds=(row.last_failure_at - row.started_at).total_seconds(),
            ongoing=bool(row.ongoing),
        )
        for row in rows
    ]


async def recent_checks(
    session: AsyncSession, *, since: datetime, per_endpoint: int = 30
) -> list[EndpointRecentChecks]:
    """Last N checks of every endpoint in ONE query (ROW_NUMBER() per endpoint), for sparklines."""
    rn = (
        func.row_number()
        .over(partition_by=CheckResult.endpoint_id, order_by=CheckResult.checked_at.desc())
        .label("rn")
    )
    ranked = (
        select(
            CheckResult.endpoint_id,
            CheckResult.checked_at,
            CheckResult.response_time_ms,
            CheckResult.is_success,
            CheckResult.status_code,
            rn,
        )
        .where(CheckResult.checked_at >= since)
        .subquery()
    )
    stmt = (
        select(ranked)
        .where(ranked.c.rn <= per_endpoint)
        .order_by(ranked.c.endpoint_id, ranked.c.checked_at)
    )
    grouped: dict[int, list[RecentCheck]] = defaultdict(list)
    for row in (await session.execute(stmt)).mappings():
        grouped[row["endpoint_id"]].append(
            RecentCheck(
                checked_at=row["checked_at"],
                response_time_ms=row["response_time_ms"],
                is_success=bool(row["is_success"]),
                status_code=row["status_code"],
            )
        )
    return [EndpointRecentChecks(endpoint_id=k, checks=v) for k, v in grouped.items()]


# One row per (endpoint, day) - including days with no checks - via generate_series + CROSS JOIN.
_DAILY_UPTIME_SQL = """
WITH days AS (
    SELECT generate_series(:start, :end, interval '1 day') AS day
)
SELECT
    e.id                                         AS endpoint_id,
    d.day                                        AS day,
    COUNT(r.id)                                  AS total_checks,
    ROUND(100.0 * COUNT(r.id) FILTER (WHERE r.is_success)
          / NULLIF(COUNT(r.id), 0), 3)           AS uptime_pct
FROM endpoints e
CROSS JOIN days d
LEFT JOIN check_results r
       ON r.endpoint_id = e.id
      AND r.checked_at >= d.day
      AND r.checked_at <  d.day + interval '1 day'
      AND NOT r.in_maintenance
{where}
GROUP BY e.id, d.day
ORDER BY e.id, d.day
"""


async def daily_uptime(
    session: AsyncSession,
    *,
    days: int,
    endpoint_id: int | None = None,
    public_only: bool = False,
) -> dict[int, list[DailyUptime]]:
    _require_postgres(session)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    conditions = []
    params: dict = {"start": start, "end": today}
    if endpoint_id is not None:
        conditions.append("e.id = :endpoint_id")
        params["endpoint_id"] = endpoint_id
    if public_only:
        conditions.append("e.is_public AND e.is_active")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    stmt = text(_DAILY_UPTIME_SQL.format(where=where)).bindparams(
        bindparam("start", type_=DateTime(timezone=True)),
        bindparam("end", type_=DateTime(timezone=True)),
    )
    result: dict[int, list[DailyUptime]] = defaultdict(list)
    for row in (await session.execute(stmt, params)).mappings():
        day = row["day"]
        result[row["endpoint_id"]].append(
            DailyUptime(
                day=day.date() if isinstance(day, datetime) else date.fromisoformat(str(day)[:10]),
                total_checks=row["total_checks"],
                uptime_pct=float(row["uptime_pct"]) if row["uptime_pct"] is not None else None,
            )
        )
    return dict(result)
