"""Assessment suite: registers the evals that run under ``python -m evals``."""

from __future__ import annotations

import time

from evals.assessment.dataset import CALIBRATION_CASES, CASES, CEFR_ORDER, DATASET_VERSION
from evals.harness import EvalResult
from src.assessment.cefr_profile import confidence_from, mastery_to_cefr
from src.evaluation.calibration import calibration_error
from src.evaluation.metrics import mean_absolute_error, pearson_correlation

_SUITE_NAME = "assessment"

# Targets. Band-ordinal MAE of <= 1 means predictions land within one CEFR
# band of the expert label; correlation should be strongly positive; ECE
# follows the same bar the grammar/verifier calibration checks use.
_MAX_BAND_MAE = 1.0
_MIN_CORRELATION = 0.9
_MAX_ECE = 0.2


def _ordinal(cefr: str) -> float:
    return float(CEFR_ORDER.index(cefr))


async def eval_correlation_and_absolute_error() -> EvalResult:
    """Predicted-vs-expert CEFR band: Pearson correlation and mean absolute error.

    Both are computed over CEFR *band ordinals* (A1=0 .. C2=5) rather than raw
    mastery, since the expert label in the dataset is a band, not a mastery
    score — this mirrors how a real correlation-with-expert-ratings study would
    compare an ordinal proficiency scale.
    """
    start = time.perf_counter()
    pairs: list[tuple[float, float]] = []
    for case in CASES:
        predicted = mastery_to_cefr(case.mastery)
        pairs.append((_ordinal(predicted), _ordinal(case.expert_cefr)))

    correlation = pearson_correlation(pairs)
    mae = mean_absolute_error(pairs)
    duration_ms = (time.perf_counter() - start) * 1000
    passed = correlation >= _MIN_CORRELATION and mae <= _MAX_BAND_MAE
    return EvalResult(
        suite=_SUITE_NAME,
        name="correlation_and_absolute_error",
        passed=passed,
        duration_ms=duration_ms,
        metrics={
            "correlation": round(correlation, 3),
            "band_mae": round(mae, 3),
            "cases": len(CASES),
        },
        detail=(
            f"dataset={DATASET_VERSION} "
            f"(target correlation>={_MIN_CORRELATION}, band_mae<={_MAX_BAND_MAE})"
        ),
    )


async def eval_calibration() -> EvalResult:
    """Whether ``confidence_from`` is calibrated: does stated confidence track
    how often the point-estimate band actually held up?

    Uses :data:`CALIBRATION_CASES` (a labeled mix of hits/misses at each
    confidence level), not :data:`CASES` — in ``CASES`` the expert label is
    defined to equal the predicted band (it tests the mapping's ordering, via
    the correlation/MAE eval above), so every prediction there is "correct" by
    construction and cannot exercise calibration meaningfully.
    """
    start = time.perf_counter()
    predictions: list[tuple[float, bool]] = [
        (confidence_from(c.uncertainty, c.sample_size), c.matched_expert_band)
        for c in CALIBRATION_CASES
    ]

    ece = calibration_error(predictions)
    duration_ms = (time.perf_counter() - start) * 1000
    passed = ece <= _MAX_ECE
    return EvalResult(
        suite=_SUITE_NAME,
        name="calibration",
        passed=passed,
        duration_ms=duration_ms,
        metrics={"ece": round(ece, 3), "predictions": len(predictions)},
        detail=f"dataset={DATASET_VERSION} ECE={ece:.3f} (target <= {_MAX_ECE})",
    )


async def eval_confidence_coverage() -> EvalResult:
    """Confidence tracks evidence: low-sample/high-uncertainty cases score lower.

    This is the "confidence coverage" metric in spirit: it does not require a
    human rater, but checks the monotonicity property any trustworthy coverage
    curve depends on — more/better evidence must not produce lower confidence.
    """
    start = time.perf_counter()
    well_evidenced = [c for c in CASES if c.sample_size >= 10]
    low_evidence = [c for c in CASES if c.sample_size < 10]
    mean_conf_high = sum(
        confidence_from(c.uncertainty, c.sample_size) for c in well_evidenced
    ) / len(well_evidenced)
    mean_conf_low = (
        sum(confidence_from(c.uncertainty, c.sample_size) for c in low_evidence) / len(low_evidence)
        if low_evidence
        else 0.0
    )
    duration_ms = (time.perf_counter() - start) * 1000
    passed = mean_conf_high > mean_conf_low
    return EvalResult(
        suite=_SUITE_NAME,
        name="confidence_coverage",
        passed=passed,
        duration_ms=duration_ms,
        metrics={
            "mean_confidence_well_evidenced": round(mean_conf_high, 3),
            "mean_confidence_low_evidence": round(mean_conf_low, 3),
        },
        detail=f"dataset={DATASET_VERSION} (well-evidenced confidence must exceed low-evidence)",
    )


SUITE = [eval_correlation_and_absolute_error, eval_calibration, eval_confidence_coverage]
