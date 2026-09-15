"""Vocabulary suite: registers the evals that run under ``python -m evals``."""

from __future__ import annotations

import time

from evals.harness import EvalResult
from evals.vocabulary.dataset import CASES, DATASET_VERSION
from src.agents.vocabulary import _parse_vocabulary_response
from src.evaluation.metrics import PrecisionRecallResult

_SUITE_NAME = "vocabulary"

# Extraction should be exact on this dataset (no partial credit): every word
# expected must be recovered, and nothing extra invented.
_MIN_F1 = 0.95


async def eval_extraction_precision_recall_f1() -> EvalResult:
    """Precision/recall/F1 of vocabulary extraction against labeled responses."""
    start = time.perf_counter()
    tp = fp = fn = 0
    for case in CASES:
        extracted = {item["word"] for item in _parse_vocabulary_response(case.raw_response)}
        tp += len(extracted & case.expected_words)
        fp += len(extracted - case.expected_words)
        fn += len(case.expected_words - extracted)

    result = PrecisionRecallResult.from_counts(tp=tp, fp=fp, fn=fn)
    duration_ms = (time.perf_counter() - start) * 1000
    passed = result.f1 >= _MIN_F1
    return EvalResult(
        suite=_SUITE_NAME,
        name="extraction_precision_recall_f1",
        passed=passed,
        duration_ms=duration_ms,
        metrics={**result.as_dict(), "cases": len(CASES)},
        detail=f"dataset={DATASET_VERSION} (target F1>={_MIN_F1})",
    )


async def eval_extraction_never_raises() -> EvalResult:
    """Malformed/empty input must degrade to an empty list, never raise.

    This is a robustness check distinct from accuracy: the parser sits between
    an LLM's raw text and the rest of the turn, so it must be exception-safe
    for every input in the dataset (including the malformed/empty cases).
    """
    start = time.perf_counter()
    failures: list[str] = []
    for case in CASES:
        try:
            _parse_vocabulary_response(case.raw_response)
        except Exception as exc:  # noqa: BLE001 - we want to record, not raise
            failures.append(f"{case.name}: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    passed = not failures
    return EvalResult(
        suite=_SUITE_NAME,
        name="extraction_never_raises",
        passed=passed,
        duration_ms=duration_ms,
        metrics={"cases": len(CASES), "failures": len(failures)},
        detail="; ".join(failures) if failures else "no exceptions",
    )


SUITE = [eval_extraction_precision_recall_f1, eval_extraction_never_raises]
