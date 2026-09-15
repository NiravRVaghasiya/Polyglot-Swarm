"""Regression suite: registers the evals that run under ``python -m evals``."""

from __future__ import annotations

import time

from evals.harness import EvalResult

_SUITE_NAME = "regression"


async def eval_no_regression_gate() -> EvalResult:
    """Roll up grammar, vocabulary, and assessment into a single pass/fail gate."""
    start = time.perf_counter()
    from evals.assessment import suite as assessment_suite
    from evals.grammar import suite as grammar_suite
    from evals.vocabulary import suite as vocabulary_suite

    checked = [*grammar_suite.SUITE, *vocabulary_suite.SUITE, *assessment_suite.SUITE]
    results = [await one() for one in checked]

    failing = [r.name for r in results if not r.passed]
    duration_ms = (time.perf_counter() - start) * 1000
    return EvalResult(
        suite=_SUITE_NAME,
        name="no_regression_gate",
        passed=not failing,
        duration_ms=duration_ms,
        metrics={"checked": len(results), "failing": len(failing)},
        detail=f"failing={failing}" if failing else "all rolled-up suites passed",
    )


SUITE = [eval_no_regression_gate]
