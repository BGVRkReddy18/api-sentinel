from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware current UTC time. All timestamps in the system are UTC."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Treat naive datetimes (e.g. read back from SQLite) as UTC so they compare with aware ones."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
