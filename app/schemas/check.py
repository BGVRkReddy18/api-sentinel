from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    endpoint_id: int
    checked_at: datetime
    status_code: int | None
    response_time_ms: float | None
    is_success: bool
    error_type: str | None
    error_message: str | None
    attempts: int
    is_anomaly: bool
    anomaly_score: float | None
    in_maintenance: bool = False
