"""Latency anomaly detection using a robust (median/MAD) z-score.

Mean/std-dev z-scores are skewed by the very outliers they try to detect. The modified z-score
(Iglewicz & Hoaglin) uses the median and the median absolute deviation (MAD), so a few past
spikes in the baseline window do not hide new ones:

    score = 0.6745 * (x - median) / MAD          anomaly if score > 3.5

Only slowdowns are flagged (one-sided): an endpoint getting faster is not an incident.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median

MAD_SCALE = 0.6745  # makes MAD consistent with the std-dev of a normal distribution


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    is_anomaly: bool
    score: float | None = None
    baseline_median_ms: float | None = None
    samples: int = 0


NOT_EVALUATED = AnomalyResult(is_anomaly=False)


def detect_latency_anomaly(
    history_ms: Iterable[float | None],
    current_ms: float,
    *,
    threshold: float = 3.5,
    min_samples: int = 10,
    min_relative_spread: float = 0.05,
    min_absolute_spread_ms: float = 1.0,
    min_delta_ms: float = 100.0,
    min_ratio: float = 1.5,
) -> AnomalyResult:
    """Score `current_ms` against recent latencies.

    The spread is floored (5% of the median, and at least 1 ms) so a perfectly stable endpoint
    (MAD == 0) does not turn sub-millisecond jitter into an alert storm.

    Statistical significance alone is not enough: 29 ms vs a 13 ms baseline is a huge z-score but
    nobody cares. A slowdown must also be practically significant - at least `min_delta_ms` slower
    AND `min_ratio` times the baseline - before it counts as an anomaly.
    """
    samples = [x for x in history_ms if x is not None and math.isfinite(x)]
    if len(samples) < min_samples or not math.isfinite(current_ms):
        return AnomalyResult(is_anomaly=False, samples=len(samples))

    baseline = median(samples)
    mad = median(abs(x - baseline) for x in samples)
    spread = max(mad, baseline * min_relative_spread, min_absolute_spread_ms)
    score = MAD_SCALE * (current_ms - baseline) / spread

    practically_significant = (
        current_ms - baseline >= min_delta_ms and current_ms >= baseline * min_ratio
    )
    return AnomalyResult(
        is_anomaly=score > threshold and practically_significant,
        score=round(score, 3),
        baseline_median_ms=round(baseline, 3),
        samples=len(samples),
    )
