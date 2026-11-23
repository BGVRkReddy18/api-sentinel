import math

import pytest

from app.services.anomaly import detect_latency_anomaly

STABLE = [100, 102, 98, 101, 99, 103, 97, 100, 101, 99, 100, 102]


def test_not_evaluated_with_too_few_samples():
    result = detect_latency_anomaly([100, 101, 99], 5000, min_samples=10)
    assert not result.is_anomaly
    assert result.score is None
    assert result.samples == 3


def test_flags_latency_spike():
    result = detect_latency_anomaly(STABLE, 400)
    assert result.is_anomaly
    assert result.score > 3.5
    assert result.baseline_median_ms == pytest.approx(100, abs=1)


def test_normal_value_is_not_flagged():
    assert not detect_latency_anomaly(STABLE, 104).is_anomaly


def test_faster_than_usual_is_not_an_anomaly():
    result = detect_latency_anomaly(STABLE, 10)
    assert not result.is_anomaly
    assert result.score < 0


def test_robust_to_outliers_in_history():
    # Past spikes in the baseline must not mask a new one (mean/std z-score would fail here).
    history = STABLE + [2000, 2500, 1800]
    assert detect_latency_anomaly(history, 450).is_anomaly


def test_zero_spread_does_not_flag_tiny_jitter():
    flat = [50.0] * 20  # MAD == 0
    assert not detect_latency_anomaly(flat, 51.5).is_anomaly
    assert detect_latency_anomaly(flat, 300).is_anomaly


def test_statistically_odd_but_tiny_slowdown_is_ignored():
    # 29 ms vs a 13 ms baseline: enormous z-score, but only +16 ms - not worth an alert.
    fast = [12, 13, 13, 14, 12, 13, 13, 12, 14, 13, 13, 12]
    result = detect_latency_anomaly(fast, 29)
    assert result.score > 3.5
    assert not result.is_anomaly


def test_slowdown_must_be_relative_too():
    # +150 ms on a 2 s endpoint is only 1.07x - not an anomaly.
    slow = [2000, 2010, 1990, 2005, 1995, 2000, 2002, 1998, 2001, 1999]
    assert not detect_latency_anomaly(slow, 2150).is_anomaly


def test_ignores_none_and_non_finite_history():
    history = [*STABLE, None, math.nan, math.inf]
    result = detect_latency_anomaly(history, 400)
    assert result.samples == len(STABLE)
    assert result.is_anomaly
