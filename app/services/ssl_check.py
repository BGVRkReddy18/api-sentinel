"""TLS certificate expiry probe."""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

SslProbe = Callable[[str, int], Awaitable[datetime]]


@dataclass(frozen=True, slots=True)
class SslInfo:
    checked_at: datetime
    expires_at: datetime | None
    error: str | None = None


async def fetch_certificate_expiry(host: str, port: int = 443, timeout: float = 10.0) -> datetime:
    """Open a verified TLS connection and return the certificate's notAfter time (UTC)."""
    context = ssl.create_default_context()
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=context, server_hostname=host), timeout
    )
    try:
        certificate = writer.get_extra_info("peercert")
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    if not certificate or "notAfter" not in certificate:
        raise ssl.SSLError("server did not present a certificate")
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(certificate["notAfter"]), tz=timezone.utc)
