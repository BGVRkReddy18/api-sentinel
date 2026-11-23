"""Async HTTP health-check engine with timeouts, assertions and exponential-backoff retries."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

import httpx

from app.core.clock import utcnow
from app.domain import ErrorType

Sleep = Callable[[float], Awaitable[None]]

# Transient failures worth retrying. Deterministic failures (4xx, body mismatch) are not retried.
RETRYABLE_ERRORS = frozenset({ErrorType.TIMEOUT, ErrorType.CONNECTION, ErrorType.UNKNOWN})
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ERROR_MESSAGE_LENGTH = 500


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """Everything needed to run a check, detached from the ORM so it is safe to use concurrently."""

    endpoint_id: int
    name: str
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    expected_status: int = 200
    expected_body_contains: str | None = None
    max_latency_ms: int | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    ssl_checked_at: datetime | None = None

    @classmethod
    def from_endpoint(cls, endpoint: Any) -> CheckSpec:
        return cls(
            endpoint_id=endpoint.id,
            name=endpoint.name,
            url=endpoint.url,
            method=endpoint.method,
            headers=dict(endpoint.headers or {}),
            body=endpoint.body,
            expected_status=endpoint.expected_status,
            expected_body_contains=endpoint.expected_body_contains,
            max_latency_ms=endpoint.max_latency_ms,
            timeout_seconds=endpoint.timeout_seconds,
            max_retries=endpoint.max_retries,
            retry_backoff_seconds=endpoint.retry_backoff_seconds,
            ssl_checked_at=endpoint.ssl_checked_at,
        )


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    checked_at: datetime
    is_success: bool
    status_code: int | None = None
    response_time_ms: float | None = None
    error_type: ErrorType | None = None
    error_message: str | None = None
    attempts: int = 1

    @property
    def is_degraded(self) -> bool:
        return self.is_success and self.error_type is ErrorType.SLOW


class HealthChecker:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        sleep: Sleep = asyncio.sleep,
        jitter_ratio: float = 0.1,
        rng: random.Random | None = None,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._jitter_ratio = jitter_ratio
        self._rng = rng or random.Random()

    def backoff_delay(self, spec: CheckSpec, failed_attempt: int) -> float:
        """Exponential backoff (base * 2^(n-1)) plus up to `jitter_ratio` random jitter."""
        base = spec.retry_backoff_seconds * (2 ** (failed_attempt - 1))
        return base + base * self._jitter_ratio * self._rng.random()

    async def run(self, spec: CheckSpec) -> CheckOutcome:
        total_attempts = spec.max_retries + 1
        for attempt in range(1, total_attempts + 1):
            outcome = await self._attempt(spec)
            if outcome.is_success or not self.should_retry(outcome) or attempt == total_attempts:
                return replace(outcome, attempts=attempt)
            await self._sleep(self.backoff_delay(spec, attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def should_retry(outcome: CheckOutcome) -> bool:
        if outcome.error_type in RETRYABLE_ERRORS:
            return True
        return (
            outcome.error_type is ErrorType.UNEXPECTED_STATUS
            and outcome.status_code in RETRYABLE_STATUS
        )

    async def _attempt(self, spec: CheckSpec) -> CheckOutcome:
        checked_at = utcnow()
        start = time.perf_counter()

        def elapsed_ms() -> float:
            return round((time.perf_counter() - start) * 1000, 3)

        def failure(error: ErrorType, message: str, status: int | None = None) -> CheckOutcome:
            return CheckOutcome(
                checked_at=checked_at,
                is_success=False,
                status_code=status,
                response_time_ms=elapsed_ms(),
                error_type=error,
                error_message=message[:MAX_ERROR_MESSAGE_LENGTH],
            )

        try:
            response = await self._client.request(
                spec.method,
                spec.url,
                headers=spec.headers,
                content=spec.body,
                timeout=spec.timeout_seconds,
            )
        except httpx.TimeoutException as exc:  # must precede TransportError (its parent)
            return failure(
                ErrorType.TIMEOUT, f"timed out after {spec.timeout_seconds}s ({type(exc).__name__})"
            )
        except httpx.TransportError as exc:
            return failure(ErrorType.CONNECTION, f"{type(exc).__name__}: {exc}")
        except httpx.HTTPError as exc:
            return failure(ErrorType.UNKNOWN, f"{type(exc).__name__}: {exc}")

        latency = elapsed_ms()
        status = response.status_code

        if status != spec.expected_status:
            return failure(
                ErrorType.UNEXPECTED_STATUS,
                f"expected HTTP {spec.expected_status}, got {status}",
                status,
            )
        if spec.expected_body_contains and spec.expected_body_contains not in response.text:
            return failure(
                ErrorType.BODY_MISMATCH,
                f"response body does not contain {spec.expected_body_contains!r}",
                status,
            )
        if spec.max_latency_ms is not None and latency > spec.max_latency_ms:
            return CheckOutcome(
                checked_at=checked_at,
                is_success=True,
                status_code=status,
                response_time_ms=latency,
                error_type=ErrorType.SLOW,
                error_message=f"latency {latency:.0f} ms exceeded SLO of {spec.max_latency_ms} ms",
            )
        return CheckOutcome(
            checked_at=checked_at, is_success=True, status_code=status, response_time_ms=latency
        )
