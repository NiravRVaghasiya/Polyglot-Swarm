"""Shared classification and regression metrics for the evaluation harness.

``benchmarks/grammar_bench.py`` computes precision/recall/false-correction-rate
inline, by hand, with no shared helper — fine for one benchmark, but the
Phase 18 evaluation harness (:mod:`evals`) needs the same arithmetic across
grammar, vocabulary, assessment, and curriculum suites, plus a couple of
regression metrics (absolute error, correlation) that didn't exist anywhere
yet. This module is that shared, tested foundation.

Calibration (Expected Calibration Error / reliability buckets) already has a
home in :mod:`src.evaluation.calibration` and is reused as-is rather than
duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass


def precision(tp: int, fp: int) -> float:
    """TP / (TP + FP). Defined as 1.0 when there were no positive predictions."""
    denom = tp + fp
    return tp / denom if denom else 1.0


def recall(tp: int, fn: int) -> float:
    """TP / (TP + FN). Defined as 1.0 when there were no positive cases."""
    denom = tp + fn
    return tp / denom if denom else 1.0


def f1_score(precision_value: float, recall_value: float) -> float:
    """Harmonic mean of precision and recall. 0.0 when both are 0."""
    denom = precision_value + recall_value
    return 2 * precision_value * recall_value / denom if denom else 0.0


def false_positive_rate(fp: int, negatives: int) -> float:
    """FP / (# actual negatives). 0.0 when there were no negative cases."""
    return fp / negatives if negatives else 0.0


@dataclass(frozen=True)
class PrecisionRecallResult:
    """Precision/recall/F1 derived from a confusion-matrix count."""

    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float

    @classmethod
    def from_counts(cls, tp: int, fp: int, fn: int) -> PrecisionRecallResult:
        """Build a result from raw TP/FP/FN counts, computing the derived rates."""
        p = precision(tp, fp)
        r = recall(tp, fn)
        return cls(tp=tp, fp=fp, fn=fn, precision=p, recall=r, f1=f1_score(p, r))

    def as_dict(self) -> dict[str, float | int]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


def mean_absolute_error(pairs: list[tuple[float, float]]) -> float:
    """Mean of ``|predicted - actual|`` over ``(predicted, actual)`` pairs.

    Returns 0.0 for an empty input (no error observed because nothing was
    measured — callers should treat an empty eval set as inconclusive, not as a
    perfect score, when deciding whether a suite passes).
    """
    if not pairs:
        return 0.0
    return sum(abs(p - a) for p, a in pairs) / len(pairs)


def pearson_correlation(pairs: list[tuple[float, float]]) -> float:
    """Pearson correlation coefficient between two paired series, in [-1, 1].

    Returns 0.0 for fewer than two points or when either series is constant
    (zero variance), since correlation is undefined there.
    """
    n = len(pairs)
    if n < 2:
        return 0.0
    xs = [p for p, _ in pairs]
    ys = [a for _, a in pairs]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = (var_x * var_y) ** 0.5
    return covariance / denom if denom else 0.0
