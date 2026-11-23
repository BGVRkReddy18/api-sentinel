from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.domain import AlertKind, AlertSeverity

if TYPE_CHECKING:
    from app.models.endpoint import Endpoint


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_endpoint_kind_created", "endpoint_id", "kind", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("endpoints.id", ondelete="CASCADE"))
    kind: Mapped[AlertKind] = mapped_column(str_enum(AlertKind))
    severity: Mapped[AlertSeverity] = mapped_column(str_enum(AlertSeverity, 16))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified: Mapped[bool] = mapped_column(Boolean, default=False)

    endpoint: Mapped[Endpoint] = relationship(back_populates="alerts", lazy="raise")
