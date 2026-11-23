from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain import AlertKind, AlertSeverity


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    kind: AlertKind
    severity: AlertSeverity
    message: str
    created_at: datetime
    resolved_at: datetime | None
    notified: bool
