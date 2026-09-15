"""Phase 18 tests: the assessment eval suite (dataset + metrics)."""

from __future__ import annotations

from evals.assessment.dataset import CALIBRATION_CASES, CASES
from evals.assessment.suite import (
    SUITE,
    eval_calibration,
    eval_confidence_coverage,
    eval_correlation_and_absolute_error,
)


class TestDataset:
    def test_covers_every_cefr_band(self):
        assert {c.expert_cefr for c in CASES} == {"A1", "A2", "B1", "B2", "C1", "C2"}

    def test_calibration_dataset_has_hits_and_misses_per_band(self):
        # A meaningful calibration dataset needs both outcomes, not a set
        # that's "correct" by construction (see suite.py's eval_calibration
        # docstring for why CASES itself can't be used for this).
        assert any(c.matched_expert_band for c in CALIBRATION_CASES)
        assert any(not c.matched_expert_band for c in CALIBRATION_CASES)


class TestCorrelationEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_correlation_and_absolute_error()
        assert result.passed
        assert result.metrics["correlation"] >= 0.9
        assert result.metrics["band_mae"] <= 1.0


class TestCalibrationEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_calibration()
        assert result.passed
        assert result.metrics["ece"] <= 0.2

    async def test_uses_the_calibration_dataset_not_the_correlation_dataset(self):
        result = await eval_calibration()
        assert result.metrics["predictions"] == len(CALIBRATION_CASES)


class TestConfidenceCoverageEval:
    async def test_well_evidenced_beats_low_evidence(self):
        result = await eval_confidence_coverage()
        assert result.passed
        assert (
            result.metrics["mean_confidence_well_evidenced"]
            > result.metrics["mean_confidence_low_evidence"]
        )


class TestSuiteRegistration:
    def test_suite_exports_all_three_evals(self):
        assert set(SUITE) == {
            eval_correlation_and_absolute_error,
            eval_calibration,
            eval_confidence_coverage,
        }
