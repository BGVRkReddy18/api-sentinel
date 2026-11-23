from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables prefixed with SENTINEL_."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="SENTINEL_", extra="ignore")

    app_name: str = "API Sentinel"
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = True

    # Accepts postgres://, postgresql:// or postgresql+asyncpg:// URLs (Render, Supabase, Neon...).
    database_url: str = "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"
    db_pool_size: int = Field(10, ge=1)
    db_max_overflow: int = Field(10, ge=0)

    # Public URL of this deployment (Render sets RENDER_EXTERNAL_URL automatically).
    public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SENTINEL_PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"),
    )

    # Optional admin key protecting all write operations (sent as the X-API-Key header).
    api_key: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=list)

    # Security: refuse to monitor private/loopback/link-local addresses (SSRF protection).
    block_private_targets: bool = False

    # Scheduler
    scheduler_enabled: bool = True
    scheduler_tick_seconds: float = Field(2.0, gt=0)
    max_concurrent_checks: int = Field(100, ge=1)

    # Data retention
    retention_days: int = Field(30, ge=1)
    retention_interval_seconds: int = Field(3600, ge=60)

    # Alerting
    alert_webhook_url: str | None = None
    alert_failure_threshold: int = Field(2, ge=1)
    alert_cooldown_seconds: int = Field(900, ge=0)

    # Email alerts. "brevo" sends over HTTPS (works on hosts that block SMTP, e.g. Render free);
    # "smtp" uses any SMTP server (Gmail app password, Mailtrap...) for local/self-hosted runs.
    email_provider: Literal["none", "brevo", "smtp"] = "none"
    email_from: str | None = None  # must be a verified sender for Brevo
    email_from_name: str = "API Sentinel"
    alert_email_to: str | None = None  # optional: receives every alert, in addition to per-endpoint emails
    brevo_api_key: SecretStr | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True

    # Latency anomaly detection (robust z-score over recent successful checks)
    anomaly_window: int = Field(50, ge=5)
    anomaly_min_samples: int = Field(10, ge=3)
    anomaly_threshold: float = Field(3.5, gt=0)
    anomaly_min_delta_ms: float = Field(100.0, ge=0)  # ignore slowdowns smaller than this
    anomaly_min_ratio: float = Field(1.5, ge=1)  # ...or less than 1.5x the baseline

    # TLS certificate monitoring
    ssl_checks_enabled: bool = True
    ssl_check_interval_hours: float = Field(6.0, gt=0)
    ssl_warning_days: int = Field(14, ge=1)

    # Built-in demo API at /demo and automatic demo endpoints on first boot
    enable_demo_target: bool = True
    seed_demo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
