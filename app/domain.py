"""Domain enums shared by the ORM, API schemas and services (no framework dependencies)."""

from enum import Enum


class EndpointStatus(str, Enum):
    UNKNOWN = "unknown"
    UP = "up"
    DEGRADED = "degraded"  # responding correctly but slower than its latency SLO
    DOWN = "down"


class ErrorType(str, Enum):
    TIMEOUT = "timeout"
    CONNECTION = "connection_error"
    UNEXPECTED_STATUS = "unexpected_status"
    BODY_MISMATCH = "body_mismatch"
    SLOW = "slow"  # succeeded, but breached max_latency_ms
    UNKNOWN = "unknown"


class AlertKind(str, Enum):
    DOWN = "down"
    RECOVERED = "recovered"
    LATENCY_ANOMALY = "latency_anomaly"
    SSL_EXPIRING = "ssl_expiring"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
