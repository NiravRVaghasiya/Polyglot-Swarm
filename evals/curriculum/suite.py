"""Curriculum suite: registers the evals that run under ``python -m evals``."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from evals.curriculum.dataset import COVERAGE_CASES, DATASET_VERSION, SKILL_BALANCE_CASES
from evals.harness import EvalResult, isolated_storage

_SUITE_NAME = "curriculum"

_MIN_COVERAGE = 1.0  # every expected target must be covered
_MIN_SKILL_BALANCE_HIT_RATE = 1.0  # every case's weak skill must appear in its plan
#: The UI's default plan length; coverage here is reported, not gated.
_DEFAULT_MINUTES = 15.0


def _seed_grammar_errors(user_id: str, errors: tuple[tuple[str, int], ...]) -> None:
    """Record grammar errors as evidence, one per session, oldest first."""
    from src.evidence import store
    from src.evidence.events import EventType, LearningEvent
    from src.evidence.provenance import Provenance

    now = datetime.now(UTC)
    store.record_events(
        [
            LearningEvent.create(
                EventType.GRAMMAR_ERROR,
                user_id,
                "Spanish",
                provenance=Provenance(source="eval", session_id=f"{construction}-s{i}"),
                skill="grammar",
                subskill=construction,
                objective_id=f"grammar.{construction}",
                item_id=f"{construction}#{i}",
                assessment="incorrect",
                confidence=0.9,
                created_at=(now - timedelta(days=occurrences - i)).isoformat(),
            )
            for construction, occurrences in errors
            for i in range(occurrences)
        ]
    )


async def eval_target_coverage() -> EvalResult:
    """Do due reviews and grammar weaknesses actually surface in the plan?"""
    start = time.perf_counter()
    async with isolated_storage():
        from src.adaptive.service import recommend
        from src.memory import vocabulary_db

        total_expected = 0
        total_covered = 0
        covered_at_default = 0
        misses: list[str] = []
        for case in COVERAGE_CASES:
            for word in case.due_words:
                vocabulary_db.upsert_word(
                    case.user_id,
                    "Spanish",
                    word,
                    next_review="2020-01-01T00:00:00+00:00",
                )
            _seed_grammar_errors(case.user_id, case.grammar_errors)

            plan = recommend(
                case.user_id,
                "Spanish",
                minutes=case.time_available_minutes,
                max_actions=case.max_actions,
                record=False,
            ).plan
            targets = {r.target for r in plan.recommendations}
            default = recommend(case.user_id, "Spanish", minutes=_DEFAULT_MINUTES, record=False)
            default_targets = {r.target for r in default.plan.recommendations}
            for expected in case.expected_targets:
                total_expected += 1
                covered_at_default += expected in default_targets
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
            "coverage_at_15_min": round(covered_at_default / total_expected, 3)
            if total_expected
            else 1.0,
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
        from src.adaptive.service import recommend
        from src.learner import get_knowledge_model

        hits = 0
        misses: list[str] = []
        for case in SKILL_BALANCE_CASES:
            for skill, assessment, count in case.events:
                # Distinct items: identical dicts are one observation since
                # ADR-0031 (duplicates no longer count as independent evidence).
                get_knowledge_model().update_from_events(
                    case.user_id,
                    "Spanish",
                    [
                        {
                            "skill": skill,
                            "assessment": assessment,
                            "confidence": 0.9,
                            "item_id": f"{skill}-{i}",
                        }
                        for i in range(count)
                    ],
                )
            plan = recommend(
                case.user_id,
                "Spanish",
                minutes=case.time_available_minutes,
                max_actions=case.max_actions,
                record=False,
            ).plan
            skills_in_plan = {r.skill for r in plan.recommendations if r.skill}
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


SUITE = [eval_target_coverage, eval_skill_balance]
