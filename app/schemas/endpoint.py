from __future__ import annotations

from datetime import datetime
from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.domain import EndpointStatus

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ALERT_EMAILS = 10


def clean_alert_emails(value: list[str] | None) -> list[str] | None:
    """Trim, lowercase, de-duplicate and validate alert recipients."""
    if value is None:
        return None
    cleaned: list[str] = []
    for raw in value:
        email = raw.strip().lower()
        if not email:
            continue
        if len(email) > 254 or not _EMAIL_RE.match(email):
            raise ValueError(f"invalid email address: {raw!r}")
        if email not in cleaned:
            cleaned.append(email)
    if len(cleaned) > MAX_ALERT_EMAILS:
        raise ValueError(f"at most {MAX_ALERT_EMAILS} alert emails per endpoint")
    return cleaned


def worst_case_check_seconds(timeout: float, retries: int, backoff: float) -> float:
    """Upper bound on one check's duration: every attempt times out + all backoff delays (+10% jitter)."""
    backoff_total = backoff * (2**retries - 1) * 1.1
    return timeout * (retries + 1) + backoff_total


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["payments-api"])
    url: HttpUrl = Field(examples=["https://api.example.com/health"])
    method: HttpMethod = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=65_536)
    expected_status: int = Field(200, ge=100, le=599)
    expected_body_contains: str | None = Field(default=None, max_length=500)
    max_latency_ms: int | None = Field(default=None, gt=0, le=600_000, description="Latency SLO")
    interval_seconds: int = Field(60, ge=10, le=86_400)
    timeout_seconds: float = Field(10.0, gt=0, le=60)
    max_retries: int = Field(2, ge=0, le=5)
    retry_backoff_seconds: float = Field(0.5, ge=0, le=30)
    is_active: bool = True
    is_public: bool = Field(False, description="Show on the public status page")
    alert_emails: list[str] = Field(default_factory=list, description="Who gets alert emails")

    _clean_emails = field_validator("alert_emails")(clean_alert_emails)

    @model_validator(mode="after")
    def _check_fits_in_interval(self) -> EndpointCreate:
        worst = worst_case_check_seconds(
            self.timeout_seconds, self.max_retries, self.retry_backoff_seconds
        )
        if worst >= self.interval_seconds:
            raise ValueError(
                f"timeout/retry policy can take up to {worst:.1f}s, which must be shorter than "
                f"interval_seconds ({self.interval_seconds}s)"
            )
        return self


class EndpointUpdate(BaseModel):
    """Partial update. Cross-field rules are re-validated against the merged result."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: HttpUrl | None = None
    method: HttpMethod | None = None
    headers: dict[str, str] | None = None
    body: str | None = Field(default=None, max_length=65_536)
    expected_status: int | None = Field(default=None, ge=100, le=599)
    expected_body_contains: str | None = Field(default=None, max_length=500)
    max_latency_ms: int | None = Field(default=None, gt=0, le=600_000)
    interval_seconds: int | None = Field(default=None, ge=10, le=86_400)
    timeout_seconds: float | None = Field(default=None, gt=0, le=60)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    retry_backoff_seconds: float | None = Field(default=None, ge=0, le=30)
    is_active: bool | None = None
    is_public: bool | None = None
    alert_emails: list[str] | None = None

    _clean_emails = field_validator("alert_emails")(clean_alert_emails)


class MaintenanceRequest(BaseModel):
    minutes: int = Field(60, ge=5, le=7 * 24 * 60)
    reason: str | None = Field(default=None, max_length=200)


class EndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    method: str
    headers: dict[str, str]
    body: str | None
    expected_status: int
    expected_body_contains: str | None
    max_latency_ms: int | None
    interval_seconds: int
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    is_active: bool
    is_public: bool
    alert_emails: list[str]
    maintenance_until: datetime | None
    maintenance_reason: str | None
    ssl_expires_at: datetime | None
    ssl_checked_at: datetime | None
    ssl_error: str | None
    current_status: EndpointStatus
    consecutive_failures: int
    last_checked_at: datetime | None
    next_check_at: datetime
    created_at: datetime
    updated_at: datetime
