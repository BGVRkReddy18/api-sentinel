from datetime import date, datetime

from pydantic import BaseModel

from app.domain import EndpointStatus


class EndpointSummary(BaseModel):
    endpoint_id: int
    name: str
    current_status: EndpointStatus
    total_checks: int
    failed_checks: int
    uptime_pct: float | None
    avg_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    p99_latency_ms: float | None
    anomalies: int


class TimeseriesPoint(BaseModel):
    bucket: datetime
    total_checks: int
    successful_checks: int
    avg_latency_ms: float | None
    p95_latency_ms: float | None


class ErrorBreakdown(BaseModel):
    error_type: str
    count: int
    last_seen: datetime


class Incident(BaseModel):
    started_at: datetime
    last_failure_at: datetime
    failed_checks: int
    duration_seconds: float
    ongoing: bool


class RecentCheck(BaseModel):
    checked_at: datetime
    response_time_ms: float | None
    is_success: bool
    status_code: int | None


class EndpointRecentChecks(BaseModel):
    endpoint_id: int
    checks: list[RecentCheck]


class DailyUptime(BaseModel):
    day: date
    total_checks: int
    uptime_pct: float | None  # None = no data that day


class StatusService(BaseModel):
    id: int
    name: str
    status: str  # up | degraded | down | maintenance | unknown
    uptime_pct: float | None
    days: list[DailyUptime]


class StatusIncident(BaseModel):
    service: str
    message: str
    started_at: datetime
    resolved_at: datetime | None


class StatusPage(BaseModel):
    overall: str  # operational | degraded | partial_outage | major_outage | maintenance
    generated_at: datetime
    services: list[StatusService]
    incidents: list[StatusIncident]
