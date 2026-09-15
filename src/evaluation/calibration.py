"""Calibration — is the stated confidence trustworthy?

A model can be confidently wrong. Calibration measures whether predicted
confidences match observed correctness: of the corrections the verifier was 90%
sure about, were ~90% actually right? This module computes Expected Calibration
Error (ECE) and reliability buckets, which the calibration benchmark (Phase 18)
and the verifier's thresholds rely on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Bucket:
    """A confidence bin's calibration summary."""

    low: float
    high: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        """Absolute miscalibration in this bucket (|confidence - accuracy|)."""
        return abs(self.mean_confidence - self.accuracy)


def reliability_buckets(
    predictions: list[tuple[float, bool]],
    *,
    n_bins: int = 10,
) -> list[Bucket]:
    """Bin (confidence, correct) pairs into equal-width reliability buckets.

    Empty buckets are omitted. ``predictions`` is a list of
    ``(confidence in [0,1], was_correct)`` pairs.
    """
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for conf, correct in predictions:
        conf = max(0.0, min(1.0, conf))
        idx = min(n_bins - 1, int(conf * n_bins))
        bins[idx].append((conf, correct))

    buckets: list[Bucket] = []
    for i, pairs in enumerate(bins):
        if not pairs:
            continue
        count = len(pairs)
        mean_conf = sum(c for c, _ in pairs) / count
        accuracy = sum(1 for _, ok in pairs if ok) / count
        buckets.append(
            Bucket(
                low=i / n_bins,
                high=(i + 1) / n_bins,
                count=count,
                mean_confidence=mean_conf,
                accuracy=accuracy,
            )
        )
    return buckets


def calibration_error(
    predictions: list[tuple[float, bool]],
    *,
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error (ECE) in [0, 1] — lower is better-calibrated.

    ECE is the sample-weighted average gap between confidence and accuracy
    across buckets. Returns 0.0 for an empty input.
    """
    buckets = reliability_buckets(predictions, n_bins=n_bins)
    total = sum(b.count for b in buckets)
    if total == 0:
        return 0.0
    return sum(b.count / total * b.gap for b in buckets)
