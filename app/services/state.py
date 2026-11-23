"""Endpoint health state machine.

    UNKNOWN/UP/DEGRADED --(N consecutive failures)--> DOWN   emits DOWN alert
    DOWN --(any success)--> UP / DEGRADED                     emits RECOVERED alert

Requiring N consecutive failures (on top of per-check retries) prevents flapping alerts.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import AlertKind, EndpointStatus


@dataclass(frozen=True, slots=True)
class Transition:
    status: EndpointStatus
    consecutive_failures: int
    events: tuple[AlertKind, ...] = ()


def evaluate_transition(
    *,
    previous: EndpointStatus,
    consecutive_failures: int,
    is_success: bool,
    is_degraded: bool,
    failure_threshold: int,
) -> Transition:
    if failure_threshold < 1:
        raise ValueError("failure_threshold must be >= 1")

    if is_success:
        status = EndpointStatus.DEGRADED if is_degraded else EndpointStatus.UP
        events = (AlertKind.RECOVERED,) if previous == EndpointStatus.DOWN else ()
        return Transition(status=status, consecutive_failures=0, events=events)

    failures = consecutive_failures + 1
    if failures >= failure_threshold:
        events = () if previous == EndpointStatus.DOWN else (AlertKind.DOWN,)
        return Transition(status=EndpointStatus.DOWN, consecutive_failures=failures, events=events)

    # Below threshold: keep the previous status, but count the failure.
    return Transition(status=previous, consecutive_failures=failures)
