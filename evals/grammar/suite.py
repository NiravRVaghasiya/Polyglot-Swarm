"""Grammar suite: registers the evals that run under ``python -m evals``."""

from __future__ import annotations

import time

from evals.grammar.dataset import CASES, DATASET_VERSION
from evals.harness import EvalResult
from src.agents.grammar import _select_errors
from src.evaluation.calibration import calibration_error
from src.evaluation.metrics import PrecisionRecallResult, false_positive_rate
from src.llm.schemas import ERROR_CLASSIFICATIONS

_SUITE_NAME = "grammar"

# Targets (plan Phase 4/18): high precision, a low false-correction rate, and a
# well-calibrated confidence signal.
_MAX_FALSE_CORRECTION_RATE = 0.1
_MAX_ECE = 0.2


async def eval_precision_recall_f1() -> EvalResult:
    """Precision/recall/F1/false-correction-rate of the classification policy."""
    start = time.perf_counter()
    tp = fp = fn = 0
    acceptable = 0
    for is_error, analysis in CASES:
        flagged = bool(_select_errors(analysis))
        if not is_error:
            acceptable += 1
        if is_error and flagged:
            tp += 1
        elif is_error and not flagged:
            fn += 1
        elif not is_error and flagged:
            fp += 1

    result = PrecisionRecallResult.from_counts(tp=tp, fp=fp, fn=fn)
    fcr = false_positive_rate(fp, acceptable)
    duration_ms = (time.perf_counter() - start) * 1000

    passed = fcr <= _MAX_FALSE_CORRECTION_RATE
    metrics: dict[str, object] = {
        **result.as_dict(),
        "false_correction_rate": round(fcr, 3),
        "cases": len(CASES),
    }
    return EvalResult(
        suite=_SUITE_NAME,
        name="precision_recall_f1",
        passed=passed,
        duration_ms=duration_ms,
        metrics=metrics,
        detail=(
            f"dataset={DATASET_VERSION} "
            f"tp={tp} fp={fp} fn={fn} (target FCR<={_MAX_FALSE_CORRECTION_RATE})"
        ),
    )


async def eval_calibration() -> EvalResult:
    """Whether stated confidence matches ground truth, for genuine error candidates.

    A proposed deviation's ``confidence`` means "P(this is a real issue worth
    teaching)" *only* when it is classified ``wrong``/``awkward`` (see
    ``grammar.GRAMMAR_PROMPT`` and ``policies.is_high_impact``) — for
    ``regional``/``informal``/``acceptable``/``formal`` cases the same field
    means confidence in *that classification*, a different quantity. Pairing
    those with the ``is_error`` label would compare confidence-of-error against
    confidence-of-acceptability, which is not a coherent calibration question.
    So this eval scores only the classifications the policy itself treats as
    candidate errors, matching what ``false_correction_rate`` above also
    gates on.
    """
    start = time.perf_counter()
    predictions: list[tuple[float, bool]] = [
        (e.confidence, is_error)
        for is_error, analysis in CASES
        for e in analysis.errors
        if e.classification.lower() in ERROR_CLASSIFICATIONS
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


SUITE = [eval_precision_recall_f1, eval_calibration]
