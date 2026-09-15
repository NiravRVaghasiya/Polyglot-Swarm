"""Phase 18 tests: the vocabulary eval suite (dataset + metrics)."""

from __future__ import annotations

from evals.vocabulary.dataset import CASES
from evals.vocabulary.suite import (
    SUITE,
    eval_extraction_never_raises,
    eval_extraction_precision_recall_f1,
)


class TestDataset:
    def test_has_positive_and_empty_cases(self):
        assert any(c.expected_words for c in CASES)
        assert any(not c.expected_words for c in CASES)

    def test_has_a_malformed_input_case(self):
        assert any("not valid json" in c.raw_response for c in CASES)


class TestExtractionEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_extraction_precision_recall_f1()
        assert result.passed
        assert result.metrics["f1"] >= 0.95

    async def test_detects_a_regression_if_extraction_breaks(self, monkeypatch):
        import evals.vocabulary.suite as suite_module

        monkeypatch.setattr(suite_module, "_parse_vocabulary_response", lambda _: [])
        result = await eval_extraction_precision_recall_f1()
        assert not result.passed


class TestNeverRaisesEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_extraction_never_raises()
        assert result.passed
        assert result.metrics["failures"] == 0

    async def test_detects_a_regression_if_parser_starts_raising(self, monkeypatch):
        import evals.vocabulary.suite as suite_module

        def _boom(_: str):
            raise ValueError("parser broke")

        monkeypatch.setattr(suite_module, "_parse_vocabulary_response", _boom)
        result = await eval_extraction_never_raises()
        assert not result.passed
        assert result.metrics["failures"] == len(CASES)


class TestSuiteRegistration:
    def test_suite_exports_both_evals(self):
        assert set(SUITE) == {eval_extraction_precision_recall_f1, eval_extraction_never_raises}
