import pytest

from app.domain import AlertKind, EndpointStatus
from app.services.state import evaluate_transition


def transition(previous, failures, *, success, degraded=False, threshold=2):
    return evaluate_transition(
        previous=previous,
        consecutive_failures=failures,
        is_success=success,
        is_degraded=degraded,
        failure_threshold=threshold,
    )


def test_first_success_marks_up_without_alert():
    t = transition(EndpointStatus.UNKNOWN, 0, success=True)
    assert t.status is EndpointStatus.UP
    assert t.events == ()


def test_single_failure_below_threshold_does_not_alert():
    t = transition(EndpointStatus.UP, 0, success=False)
    assert t.status is EndpointStatus.UP
    assert t.consecutive_failures == 1
    assert t.events == ()


def test_reaching_threshold_goes_down_and_alerts():
    t = transition(EndpointStatus.UP, 1, success=False)
    assert t.status is EndpointStatus.DOWN
    assert t.events == (AlertKind.DOWN,)


def test_already_down_does_not_re_alert():
    t = transition(EndpointStatus.DOWN, 5, success=False)
    assert t.status is EndpointStatus.DOWN
    assert t.consecutive_failures == 6
    assert t.events == ()


def test_recovery_emits_recovered_and_resets_failures():
    t = transition(EndpointStatus.DOWN, 4, success=True)
    assert t.status is EndpointStatus.UP
    assert t.consecutive_failures == 0
    assert t.events == (AlertKind.RECOVERED,)


def test_slow_success_is_degraded():
    t = transition(EndpointStatus.UP, 0, success=True, degraded=True)
    assert t.status is EndpointStatus.DEGRADED
    assert t.events == ()


def test_threshold_of_one_alerts_immediately():
    t = transition(EndpointStatus.UNKNOWN, 0, success=False, threshold=1)
    assert t.status is EndpointStatus.DOWN
    assert t.events == (AlertKind.DOWN,)


def test_invalid_threshold():
    with pytest.raises(ValueError):
        transition(EndpointStatus.UP, 0, success=False, threshold=0)
