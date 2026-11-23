from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.base import Base, str_enum
from app.domain import EndpointStatus

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.check_result import CheckResult


class Endpoint(Base):
    """A monitored API endpoint plus its live health state."""

    __tablename__ = "endpoints"
    __table_args__ = (
        # Serves the scheduler's "which endpoints are due?" query.
        Index("ix_endpoints_due", "is_active", "next_check_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    url: Mapped[str] = mapped_column(String(2048))
    method: Mapped[str] = mapped_column(String(10), default="GET")
    headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    body: Mapped[str | None] = mapped_column(Text)

    # Assertions / SLOs
    expected_status: Mapped[int] = mapped_column(Integer, default=200)
    expected_body_contains: Mapped[str | None] = mapped_column(String(500))
    max_latency_ms: Mapped[int | None] = mapped_column(Integer)

    # Check policy
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=10.0)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    retry_backoff_seconds: Mapped[float] = mapped_column(Float, default=0.5)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)  # shown on the status page
    # Owners of this API: they get DOWN / RECOVERED / anomaly / TLS emails for it.
    alert_emails: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Maintenance window: checks keep running, alerts are muted, SLA excludes these checks.
    maintenance_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maintenance_reason: Mapped[str | None] = mapped_column(String(200))

    # TLS certificate monitoring
    ssl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ssl_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ssl_error: Mapped[str | None] = mapped_column(String(300))

    # Live state, maintained by the monitor
    current_status: Mapped[EndpointStatus] = mapped_column(
        str_enum(EndpointStatus, 16), default=EndpointStatus.UNKNOWN
    )
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    results: Mapped[list[CheckResult]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
