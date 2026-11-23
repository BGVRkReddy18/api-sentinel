from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.endpoint import Endpoint


class CheckResult(Base):
    """One health check execution (time-series data, the largest table)."""

    __tablename__ = "check_results"
    __table_args__ = (
        # Composite index for per-endpoint time-range queries (history, analytics, baselines).
        Index("ix_check_results_endpoint_checked_at", "endpoint_id", "checked_at"),
        # Global time index for the retention job.
        Index("ix_check_results_checked_at", "checked_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[float | None] = mapped_column(Float)
    is_success: Mapped[bool] = mapped_column(Boolean)
    error_type: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    in_maintenance: Mapped[bool] = mapped_column(Boolean, default=False)

    endpoint: Mapped[Endpoint] = relationship(back_populates="results", lazy="raise")
