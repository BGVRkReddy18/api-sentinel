from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, WindowHours, get_endpoint_or_404, since
from app.schemas import (
    DailyUptime,
    EndpointRecentChecks,
    EndpointSummary,
    ErrorBreakdown,
    Incident,
    TimeseriesPoint,
)
from app.services import analytics
from app.services.analytics import Bucket

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=list[EndpointSummary])
async def summary(session: SessionDep, hours: WindowHours = 24, endpoint_id: int | None = None):
    """Uptime %, failure count and p50/p95/p99 latency per endpoint."""
    return await analytics.endpoint_summary(session, since=since(hours), endpoint_id=endpoint_id)


@router.get("/recent", response_model=list[EndpointRecentChecks])
async def recent(
    session: SessionDep,
    per_endpoint: Annotated[int, Query(ge=1, le=200)] = 30,
    hours: WindowHours = 24,
):
    """Last N checks of every endpoint (one window-function query) - powers the sparklines."""
    return await analytics.recent_checks(session, since=since(hours), per_endpoint=per_endpoint)


@router.get("/endpoints/{endpoint_id}/timeseries", response_model=list[TimeseriesPoint])
async def timeseries(
    endpoint_id: int,
    session: SessionDep,
    hours: WindowHours = 24,
    bucket: Annotated[Bucket, Query()] = "hour",
):
    await get_endpoint_or_404(session, endpoint_id)
    return await analytics.latency_timeseries(
        session, endpoint_id=endpoint_id, since=since(hours), bucket=bucket
    )


@router.get("/endpoints/{endpoint_id}/uptime-daily", response_model=list[DailyUptime])
async def uptime_daily(
    endpoint_id: int, session: SessionDep, days: Annotated[int, Query(ge=1, le=90)] = 30
):
    """Daily uptime %, one row per day including days without data."""
    await get_endpoint_or_404(session, endpoint_id)
    result = await analytics.daily_uptime(session, days=days, endpoint_id=endpoint_id)
    return result.get(endpoint_id, [])


@router.get("/endpoints/{endpoint_id}/errors", response_model=list[ErrorBreakdown])
async def errors(endpoint_id: int, session: SessionDep, hours: WindowHours = 24):
    await get_endpoint_or_404(session, endpoint_id)
    return await analytics.error_breakdown(session, endpoint_id=endpoint_id, since=since(hours))


@router.get("/endpoints/{endpoint_id}/incidents", response_model=list[Incident])
async def incidents(
    endpoint_id: int,
    session: SessionDep,
    hours: WindowHours = 24 * 7,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    """Outage periods (consecutive failed checks), newest first."""
    await get_endpoint_or_404(session, endpoint_id)
    return await analytics.incidents(session, endpoint_id=endpoint_id, since=since(hours), limit=limit)
