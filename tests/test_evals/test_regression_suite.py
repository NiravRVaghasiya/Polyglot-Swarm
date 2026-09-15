"""Phase 18 tests: the regression rollup suite."""

from __future__ import annotations

from evals.regression.suite import SUITE, eval_no_regression_gate


class TestNoRegressionGate:
    async def test_passes_when_all_rolled_up_suites_pass(self):
        result = await eval_no_regression_gate()
        assert result.passed
        assert result.metrics["failing"] == 0
        assert result.suite == "regression"

    async def test_reports_failing_names_when_a_suite_regresses(self, monkeypatch):
        import evals.grammar.suite as grammar_suite

        async def _always_fails():
            from evals.harness import EvalResult

            return EvalResult(
                suite="grammar", name="precision_recall_f1", passed=False, duration_ms=0.0
            )

        # eval_no_regression_gate reads grammar_suite.SUITE (the list), not the
        # eval_precision_recall_f1 attribute directly, so the list itself must
        # be patched for the rollup to see the failure.
        monkeypatch.setattr(
            grammar_suite,
            "SUITE",
            [_always_fails, grammar_suite.eval_calibration],
        )
        result = await eval_no_regression_gate()
        assert not result.passed
        assert "precision_recall_f1" in result.detail


class TestSuiteRegistration:
    def test_suite_exports_the_gate(self):
        assert SUITE == [eval_no_regression_gate]
