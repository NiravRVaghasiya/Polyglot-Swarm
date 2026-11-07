"""Statistical tools for evaluation: intervals, paired tests, calibration fits.

Everything a benchmark report needs to say *how sure* it is, not just what
it measured:

- :func:`wilson_interval` — a confidence interval for a proportion that stays
  sensible at small n and at 0% / 100% (unlike the normal approximation).
- :func:`bootstrap_ci` — a seeded percentile bootstrap for any statistic of a
  list of items (F1, ECE, a paired difference), so reports are reproducible.
- :func:`mcnemar_exact` — the exact two-sided McNemar test for *paired*
  correctness (two models, or two prompt versions, on the same cases); it uses
  only the discordant pairs, which is what makes it valid for a regression
  check on a fixed benchmark.
- :func:`cohens_kappa` — chance-corrected agreement (between annotators, or
  between providers).
- :func:`brier_score`, :func:`risk_coverage`, :func:`area_under_risk_coverage`
  — calibration and selective prediction.
- :func:`fit_platt` / :func:`fit_histogram_binning` — calibration maps. They
  must be fitted on held-out *development* data and evaluated on *test* data;
  fitting and scoring on the same data would overstate calibration.

All functions are pure and deterministic.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass


def wilson_interval(successes: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. ``(0, 1)`` when ``n == 0``."""
    if n <= 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def bootstrap_ci[T](
    items: Sequence[T],
    statistic: Callable[[Sequence[T]], float],
    *,
    samples: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap interval of ``statistic`` over resampled ``items``.

    Returns ``(nan, nan)`` for an empty input. Seeded, so the same inputs give
    the same interval.
    """
    if not items:
        return (math.nan, math.nan)
    rng = random.Random(seed)
    n = len(items)
    values = []
    for _ in range(samples):
        resample = [items[rng.randrange(n)] for _ in range(n)]
        value = statistic(resample)
        if not math.isnan(value):
            values.append(value)
    if not values:
        return (math.nan, math.nan)
    values.sort()
    lo_idx = int((alpha / 2) * (len(values) - 1))
    hi_idx = int((1 - alpha / 2) * (len(values) - 1))
    return (values[lo_idx], values[hi_idx])


def _binom_pmf(k: int, n: int) -> float:
    return math.comb(n, k) * 0.5**n


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from the discordant counts.

    ``b`` = cases the first system got right and the second wrong; ``c`` = the
    reverse. With no discordant pairs there is no evidence of a difference
    (p = 1).
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(_binom_pmf(i, n) for i in range(k + 1))
    return min(1.0, 2 * tail)


def cohens_kappa(a: Sequence[object], b: Sequence[object]) -> float:
    """Cohen's kappa between two label sequences of equal length.

    Returns 1.0 when both raters use a single identical label throughout
    (agreement is perfect but chance agreement is also 1), and ``nan`` for
    empty input.
    """
    if len(a) != len(b):
        raise ValueError("label sequences must have equal length")
    n = len(a)
    if n == 0:
        return math.nan
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    labels = set(a) | set(b)
    expected = sum((list(a).count(lbl) / n) * (list(b).count(lbl) / n) for lbl in labels)
    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def brier_score(predictions: Sequence[tuple[float, bool]]) -> float:
    """Mean squared error of probabilities against outcomes. ``nan`` if empty."""
    if not predictions:
        return math.nan
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in predictions) / len(predictions)


def risk_coverage(predictions: Sequence[tuple[float, bool]]) -> list[tuple[float, float]]:
    """Selective-prediction curve: ``(coverage, accuracy)`` when keeping the
    most confident predictions first. Ties are kept together."""
    if not predictions:
        return []
    ordered = sorted(predictions, key=lambda p: -p[0])
    n = len(ordered)
    curve: list[tuple[float, float]] = []
    correct = 0
    i = 0
    while i < n:
        j = i
        while j < n and ordered[j][0] == ordered[i][0]:
            correct += int(ordered[j][1])
            j += 1
        curve.append((j / n, correct / j))
        i = j
    return curve


def area_under_risk_coverage(predictions: Sequence[tuple[float, bool]]) -> float:
    """AURC: mean selective *risk* (1 - accuracy) over the coverage curve.

    Lower is better; a confidence signal that ranks correct predictions first
    has a lower AURC than one that does not. ``nan`` if empty.
    """
    curve = risk_coverage(predictions)
    if not curve:
        return math.nan
    area = 0.0
    prev_cov = 0.0
    for cov, acc in curve:
        area += (cov - prev_cov) * (1 - acc)
        prev_cov = cov
    return area


@dataclass(frozen=True)
class PlattMap:
    """``p = sigmoid(a * logit(c) + b)`` fitted on development data."""

    a: float
    b: float
    n: int

    def __call__(self, confidence: float) -> float:
        c = min(1 - 1e-6, max(1e-6, confidence))
        z = self.a * math.log(c / (1 - c)) + self.b
        return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def fit_platt(predictions: Sequence[tuple[float, bool]], *, iterations: int = 100) -> PlattMap:
    """Fit a Platt map by Newton's method on log-loss (with a tiny ridge).

    With degenerate data (one class only) it returns the map that keeps the
    raw confidence's ranking but cannot be trusted; callers report ``n``.
    """
    xs = [
        math.log(min(1 - 1e-6, max(1e-6, c)) / (1 - min(1 - 1e-6, max(1e-6, c))))
        for c, _ in predictions
    ]
    ys = [1.0 if y else 0.0 for _, y in predictions]
    ridge = 1e-3

    def sig(z: float) -> float:
        return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))

    def loss(a: float, b: float) -> float:
        total = 0.5 * ridge * ((a - 1.0) ** 2 + b * b)
        for x, y in zip(xs, ys, strict=True):
            z = a * x + b
            # log(1 + e^z) - y*z, computed stably.
            total += (max(z, 0.0) + math.log1p(math.exp(-abs(z)))) - y * z
        return total

    a, b = 1.0, 0.0
    current = loss(a, b)
    for _ in range(iterations):
        ga, gb = ridge * (a - 1.0), ridge * b
        haa = hbb = ridge
        hab = 0.0
        for x, y in zip(xs, ys, strict=True):
            p = sig(a * x + b)
            w = p * (1 - p)
            ga += (p - y) * x
            gb += p - y
            haa += w * x * x
            hab += w * x
            hbb += w
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        # Backtracking: plain Newton overshoots when confidences sit near 1
        # (huge logits, vanishing curvature).
        step = 1.0
        while step > 1e-8:
            na, nb = a - step * da, b - step * db
            candidate = loss(na, nb)
            if candidate <= current:
                break
            step /= 2
        else:
            break
        a, b, improvement = na, nb, current - candidate
        current = candidate
        if improvement < 1e-10:
            break
    return PlattMap(a, b, len(predictions))


@dataclass(frozen=True)
class HistogramMap:
    """Equal-width bins mapping confidence to the dev accuracy in that bin
    (Laplace-smoothed, so an empty or tiny bin falls back toward 0.5)."""

    edges: tuple[float, ...]
    values: tuple[float, ...]
    n: int

    def __call__(self, confidence: float) -> float:
        c = min(1.0, max(0.0, confidence))
        for i in range(len(self.values)):
            if c <= self.edges[i + 1] or i == len(self.values) - 1:
                return self.values[i]
        return self.values[-1]


def fit_histogram_binning(
    predictions: Sequence[tuple[float, bool]], *, bins: int = 5
) -> HistogramMap:
    """Fit histogram binning (bin accuracy with add-one smoothing)."""
    edges = tuple(i / bins for i in range(bins + 1))
    values = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        members = [y for c, y in predictions if (lo < c <= hi) or (i == 0 and c <= hi)]
        values.append((sum(1 for y in members if y) + 1) / (len(members) + 2))
    return HistogramMap(edges, tuple(values), len(predictions))


def gate_decision(
    value: float, interval: tuple[float, float], threshold: float, direction: str
) -> str:
    """``pass`` / ``fail`` / ``inconclusive`` for a threshold judged on an interval.

    ``direction="max"``: values at or below the threshold are good;
    ``"min"``: values at or above it are good. Only an interval entirely on
    one side decides; otherwise the data cannot support a verdict.
    """
    lo, hi = interval
    if math.isnan(value) or math.isnan(lo) or math.isnan(hi):
        return "inconclusive"
    if direction == "max":
        if hi <= threshold:
            return "pass"
        if lo > threshold:
            return "fail"
        return "inconclusive"
    if lo >= threshold:
        return "pass"
    if hi < threshold:
        return "fail"
    return "inconclusive"
