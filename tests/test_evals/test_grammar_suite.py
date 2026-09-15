"""Phase 18 tests: the grammar eval suite (dataset + metrics)."""

from __future__ import annotations

from evals.grammar.dataset import CASES
from evals.grammar.suite import SUITE, eval_calibration, eval_precision_recall_f1


class TestDataset:
    def test_has_both_error_and_acceptable_cases(self):
        assert any(is_error for is_error, _ in CASES)
        assert any(not is_error for is_error, _ in CASES)


class TestPrecisionRecallF1Eval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_precision_recall_f1()
        assert result.passed
        assert result.metrics["false_correction_rate"] <= 0.1
        assert result.suite == "grammar"

    async def test_metrics_include_f1(self):
        result = await eval_precision_recall_f1()
        assert "f1" in result.metrics
        assert 0.0 <= result.metrics["f1"] <= 1.0


class TestCalibrationEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_calibration()
        assert result.passed
        assert result.metrics["ece"] <= 0.2

    async def test_only_scores_genuine_error_candidates(self):
        # Regional/informal/acceptable/formal cases must not be counted, since
        # their confidence means something different (see suite.py docstring).
        result = await eval_calibration()
        genuine = sum(
            1
            for _, analysis in CASES
            for e in analysis.errors
            if e.classification.lower() in {"wrong", "awkward"}
        )
        assert result.metrics["predictions"] == genuine


class TestSuiteRegistration:
    def test_suite_exports_both_evals(self):
        assert set(SUITE) == {eval_precision_recall_f1, eval_calibration}
