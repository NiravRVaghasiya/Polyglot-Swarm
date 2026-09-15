"""Phase 18 tests: the curriculum eval suite (dataset + metrics).

These exercise the real planner against isolated SQLite storage (via
``evals.harness.isolated_storage``), so they are slower than the other eval
suite tests but still fully offline and deterministic.
"""

from __future__ import annotations

from evals.curriculum.dataset import COVERAGE_CASES, DIFFICULTY_CASES, SKILL_BALANCE_CASES
from evals.curriculum.suite import (
    SUITE,
    eval_difficulty_appropriateness,
    eval_skill_balance,
    eval_target_coverage,
)


class TestDataset:
    def test_coverage_cases_have_expected_targets(self):
        assert all(c.expected_targets for c in COVERAGE_CASES)

    def test_skill_balance_cases_cover_distinct_skills(self):
        skills = {c.expected_skill_in_plan for c in SKILL_BALANCE_CASES}
        assert len(skills) == len(SKILL_BALANCE_CASES)

    def test_difficulty_cases_cover_both_verdicts(self):
        assert any(c.expected_appropriate for c in DIFFICULTY_CASES)
        assert any(not c.expected_appropriate for c in DIFFICULTY_CASES)


class TestTargetCoverageEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_target_coverage()
        assert result.passed
        assert result.metrics["coverage"] == 1.0
        assert result.metrics["covered"] == result.metrics["expected"]


class TestSkillBalanceEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_skill_balance()
        assert result.passed
        assert result.metrics["hit_rate"] == 1.0


class TestDifficultyAppropriatenessEval:
    async def test_passes_on_the_shipped_dataset(self):
        result = await eval_difficulty_appropriateness()
        assert result.passed
        assert result.metrics["accuracy"] == 1.0

    async def test_matches_the_pure_function_directly(self):
        from src.curriculum.difficulty import difficulty_appropriate

        for case in DIFFICULTY_CASES:
            actual = difficulty_appropriate(case.mastery, fatigue=case.fatigue)
            assert actual == case.expected_appropriate, case.name


class TestSuiteRegistration:
    def test_suite_exports_all_three_evals(self):
        assert set(SUITE) == {
            eval_target_coverage,
            eval_skill_balance,
            eval_difficulty_appropriateness,
        }
