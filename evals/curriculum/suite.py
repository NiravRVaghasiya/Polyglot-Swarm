"""Curriculum suite: registers the evals that run under ``python -m evals``."""

from __future__ import annotations

import time

from evals.curriculum.dataset import (
    COVERAGE_CASES,
    DATASET_VERSION,
    DIFFICULTY_CASES,
    SKILL_BALANCE_CASES,
)
from evals.harness import EvalResult, isolated_storage

_SUITE_NAME = "curriculum"

_MIN_COVERAGE = 1.0  # every expected target must be covered
_MIN_SKILL_BALANCE_HIT_RATE = 1.0  # every case's weak skill must appear in its plan


async def eval_target_coverage() -> EvalResult:
    """Do due reviews and grammar weaknesses actually surface as plan actions?"""
    start = time.perf_counter()
    async with isolated_storage():
        from src.curriculum import plan_next_actions
        from src.memory import analytics, vocabulary_db

        total_expected = 0
        total_covered = 0
        misses: list[str] = []
        for case in COVERAGE_CASES:
            for word in case.due_words:
                vocabulary_db.upsert_word(
                    case.user_id,
                    "Spanish",
                    word,
                    next_review="2020-01-01T00:00:00+00:00",
                )
            for construction, occurrences in case.grammar_errors:
                for _ in range(occurrences):
                    analytics.record_error(case.user_id, "Spanish", construction)

            plan = plan_next_actions(case.user_id, "Spanish")
            targets = {a.target for a in plan}
            for expected in case.expected_targets:
                total_expected += 1
                if expected in targets:
                    total_covered += 1
                else:
                    misses.append(f"{case.name}:{expected}")

    coverage = total_covered / total_expected if total_expected else 1.0
    duration_ms = (time.perf_counter() - start) * 1000
    passed = coverage >= _MIN_COVERAGE
    return EvalResult(
        suite=_SUITE_NAME,
        name="target_coverage",
        passed=passed,
        duration_ms=duration_ms,
        metrics={
            "coverage": round(coverage, 3),
            "expected": total_expected,
            "covered": total_covered,
            "cases": len(COVERAGE_CASES),
        },
        detail=(
            f"dataset={DATASET_VERSION} misses={misses}" if misses else f"dataset={DATASET_VERSION}"
        ),
    )


async def eval_skill_balance() -> EvalResult:
    """Does a learner's seeded weak skill actually appear in their own plan?

    Each case is scored independently against its own plan (not pooled across
    learners), so this is a per-learner skill-balance check: the planner must
    not systematically ignore a skill the learner's evidence says is weak.
    """
    start = time.perf_counter()
    async with isolated_storage():
        from src.curriculum import PlanConstraints, plan_next_actions
        from src.learner import get_knowledge_model

        hits = 0
        misses: list[str] = []
        for case in SKILL_BALANCE_CASES:
            for skill, assessment, count in case.events:
                get_knowledge_model().update_from_events(
                    case.user_id,
                    "Spanish",
                    [{"skill": skill, "assessment": assessment, "confidence": 0.9}] * count,
                )
            constraints = PlanConstraints(
                time_available_minutes=case.time_available_minutes,
                max_actions=case.max_actions,
            )
            plan = plan_next_actions(case.user_id, "Spanish", constraints=constraints)
            skills_in_plan = {a.skill for a in plan if a.skill}
            if case.expected_skill_in_plan in skills_in_plan:
                hits += 1
            else:
                misses.append(case.name)

    hit_rate = hits / len(SKILL_BALANCE_CASES) if SKILL_BALANCE_CASES else 1.0
    duration_ms = (time.perf_counter() - start) * 1000
    passed = hit_rate >= _MIN_SKILL_BALANCE_HIT_RATE
    return EvalResult(
        suite=_SUITE_NAME,
        name="skill_balance",
        passed=passed,
        duration_ms=duration_ms,
        metrics={"hit_rate": round(hit_rate, 3), "cases": len(SKILL_BALANCE_CASES)},
        detail=(
            f"dataset={DATASET_VERSION} misses={misses}" if misses else f"dataset={DATASET_VERSION}"
        ),
    )


async def eval_difficulty_appropriateness() -> EvalResult:
    """Score :func:`difficulty_appropriate` against labeled (mastery, fatigue) cases."""
    start = time.perf_counter()
    from src.curriculum.difficulty import difficulty_appropriate

    correct = 0
    mismatches: list[str] = []
    for case in DIFFICULTY_CASES:
        actual = difficulty_appropriate(case.mastery, fatigue=case.fatigue)
        if actual == case.expected_appropriate:
            correct += 1
        else:
            mismatches.append(case.name)

    accuracy = correct / len(DIFFICULTY_CASES) if DIFFICULTY_CASES else 1.0
    duration_ms = (time.perf_counter() - start) * 1000
    passed = not mismatches
    return EvalResult(
        suite=_SUITE_NAME,
        name="difficulty_appropriateness",
        passed=passed,
        duration_ms=duration_ms,
        metrics={"accuracy": round(accuracy, 3), "cases": len(DIFFICULTY_CASES)},
        detail=(
            f"dataset={DATASET_VERSION} mismatches={mismatches}"
            if mismatches
            else f"dataset={DATASET_VERSION}"
        ),
    )


SUITE = [eval_target_coverage, eval_skill_balance, eval_difficulty_appropriateness]
