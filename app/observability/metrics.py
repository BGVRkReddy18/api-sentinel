"""Prometheus metrics exposed at /metrics."""

from __future__ import annotations

import contextlib

from prometheus_client import Counter, Gauge, Histogram

from app.domain import EndpointStatus

CHECKS_TOTAL = Counter(
    "sentinel_checks_total", "Health checks executed", ["endpoint", "outcome"]
)
CHECK_LATENCY = Histogram(
    "sentinel_check_latency_seconds",
    "Latency of successful health checks",
    ["endpoint"],
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
ENDPOINT_UP = Gauge(
    "sentinel_endpoint_up", "Endpoint health: 1=up, 0.5=degraded, 0=down", ["endpoint"]
)
ANOMALIES_TOTAL = Counter(
    "sentinel_latency_anomalies_total", "Latency anomalies detected", ["endpoint"]
)
ALERTS_TOTAL = Counter("sentinel_alerts_total", "Alerts raised", ["kind"])
SCHEDULER_TICK_SECONDS = Histogram(
    "sentinel_scheduler_tick_seconds", "Time spent claiming due endpoints per tick"
)
SCHEDULER_CLAIMED_TOTAL = Counter(
    "sentinel_scheduler_claimed_total", "Endpoints claimed for checking"
)

_STATUS_VALUE = {
    EndpointStatus.UP: 1.0,
    EndpointStatus.DEGRADED: 0.5,
    EndpointStatus.DOWN: 0.0,
}


def observe_check(
    endpoint: str,
    *,
    is_success: bool,
    is_degraded: bool,
    latency_ms: float | None,
    status: EndpointStatus,
    is_anomaly: bool,
) -> None:
    outcome = "degraded" if is_degraded else ("success" if is_success else "failure")
    CHECKS_TOTAL.labels(endpoint=endpoint, outcome=outcome).inc()
    if is_success and latency_ms is not None:
        CHECK_LATENCY.labels(endpoint=endpoint).observe(latency_ms / 1000)
    if status in _STATUS_VALUE:
        ENDPOINT_UP.labels(endpoint=endpoint).set(_STATUS_VALUE[status])
    if is_anomaly:
        ANOMALIES_TOTAL.labels(endpoint=endpoint).inc()


def forget_endpoint(endpoint: str) -> None:
    """Drop per-endpoint gauge series when an endpoint is deleted or renamed."""
    with contextlib.suppress(KeyError):
        ENDPOINT_UP.remove(endpoint)
