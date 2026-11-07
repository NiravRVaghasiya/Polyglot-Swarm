"""Phase 18 tests: the curriculum eval suite (dataset + metrics).

These exercise the real planner (the adaptive engine) against isolated SQLite
storage (via ``evals.harness.isolated_storage``), so they are slower than the
other eval suite tests but still fully offline and deterministic.
"""

from __future__ import annotations

from evals.curriculum.dataset import COVERAGE_CASES, SKILL_BALANCE_CASES
from evals.curriculum.suite import SUITE, eval_skill_balance, eval_target_coverage


class TestDataset:
    def test_coverage_cases_have_expected_targets(self):
        assert all(c.expected_targets for c in COVERAGE_CASES)

    def test_grammar_cases_use_catalog_constructions(self):
        from src.adaptive.snapshot import catalog_for_language

        catalog = {o.subskill for o in catalog_for_language("Spanish")}
        assert {c for case in COVERAGE_CASES for c, _ in case.grammar_errors} <= catalog

    def test_skill_balance_cases_cover_distinct_skills(self):
        skills = {c.expected_skill_in_plan for c in SKILL_BALANCE_CASES}
        assert len(skills) == len(SKILL_BALANCE_CASES)


class TestTargetCoverageEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_target_coverage()
        assert result.passed
        assert result.metrics["coverage"] == 1.0
        assert result.metrics["covered"] == result.metrics["expected"]
        assert 0.0 <= result.metrics["coverage_at_15_min"] <= 1.0


class TestSkillBalanceEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_skill_balance()
        assert result.passed
        assert result.metrics["hit_rate"] == 1.0


class TestSuiteRegistration:
    def test_suite_exports_both_evals(self):
        assert set(SUITE) == {eval_target_coverage, eval_skill_balance}
