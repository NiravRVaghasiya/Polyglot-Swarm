"""ADR-0031: the evidence-driven mastery engine (``lkm-evidence-v2``).

Pure-engine tests: no storage. Evidence is given as stored-row dicts.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from src.learner.estimation import (
    DEFAULT_CONFIG,
    EvidenceMasteryEngine,
    EvidenceStatus,
    fit_ability,
)

_T0 = datetime(2026, 10, 1, tzinfo=UTC)


def ev(
    n: int,
    *,
    skill: str = "grammar",
    assessment: str = "correct",
    item: str | None = None,
    session: str | None = "s1",
    confidence: float = 0.9,
    difficulty: float | None = None,
    task_type: str | None = None,
    days: float = 0.0,
    correlation: str | None = None,
    event_type: str = "SKILL_EVIDENCE",
    observed: str | None = None,
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or f"e{n}-{skill}-{item}-{session}-{assessment}-{days}",
        "event_type": event_type,
        "user_id": "u",
        "language": "Spanish",
        "skill": skill,
        "item_id": item,
        "objective_id": f"{skill}.{item}" if item else None,
        "assessment": assessment,
        "confidence": confidence,
        "session_id": session,
        "difficulty": difficulty,
        "difficulty_basis": "unknown" if difficulty is None else "measured",
        "task_type": task_type,
        "correlation_id": correlation,
        "observed": observed if observed is not None else f"obs-{n}",
        "created_at": (_T0 + timedelta(days=days)).isoformat(),
    }


def distinct(k: int, *, assessment: str = "correct", sessions: int = 1, **kw) -> list[dict]:
    return [
        ev(i, item=f"item{i}", assessment=assessment, session=f"s{i % sessions}", **kw)
        for i in range(k)
    ]


def estimate(rows, skill="grammar", **kw):
    return EvidenceMasteryEngine().estimate_all(rows, **kw)[skill]


class TestNoEvidence:
    def test_no_rows_no_estimates(self):
        assert EvidenceMasteryEngine().estimate_all([]) == {}

    def test_exposure_only_is_not_mastery(self):
        rows = [
            ev(
                i,
                skill="vocabulary",
                item=f"w{i}",
                assessment="exposed",
                event_type="VOCAB_OBSERVED",
            )
            for i in range(10)
        ]
        e = estimate(rows, skill="vocabulary")
        assert e.mastery is None  # missing graded evidence is not zero mastery
        assert e.cefr is None
        assert e.status == EvidenceStatus.INSUFFICIENT
        assert e.uncertainty == 1.0
        assert e.coverage.practiced_items == 10
        assert e.coverage.assessed_items == 0

    def test_abstain_is_not_graded(self):
        e = estimate([ev(i, item=f"x{i}", assessment="abstain") for i in range(5)])
        assert e.mastery is None and e.graded_count == 0

    def test_unmappable_assessment_ignored(self):
        e = estimate([ev(1, item="x", assessment="???")])
        assert e.mastery is None and e.raw_count == 1


class TestDuplicatesAndCorrelation:
    def test_exact_duplicates_count_once(self):
        one = estimate([ev(0, item="ser", observed="soy cansado")])
        rows = [
            {**ev(0, item="ser", observed="soy cansado"), "event_id": f"dup{i}"} for i in range(10)
        ]
        many = estimate(rows)
        assert many.raw_count == 10
        assert many.independent_count == 1
        assert many.mastery == pytest.approx(one.mastery)
        assert many.uncertainty == pytest.approx(one.uncertainty)
        assert many.quality.redundancy_share == pytest.approx(0.9)

    def test_correlated_judgments_of_one_production_count_once(self):
        # Two agents judging the same sentence about the same construction.
        rows = [
            ev(1, item="ser", correlation="c1", assessment="incorrect", observed="soy cansado"),
            {
                **ev(2, item="ser", correlation="c1", assessment="awkward", observed="x"),
                "source": "writing-agent",
            },
        ]
        e = estimate(rows)
        assert e.graded_count == 2
        assert e.independent_count == 1
        # Merged reliability is the max, not the sum.
        single = estimate([rows[0]])
        assert e.effective_n == pytest.approx(single.effective_n)

    def test_same_production_different_items_are_separate(self):
        rows = [
            ev(1, item="ser", correlation="c1", assessment="incorrect"),
            ev(2, item="gender", correlation="c1", assessment="incorrect"),
        ]
        assert estimate(rows).independent_count == 2


class TestRepetition:
    def test_repeating_one_item_cannot_inflate(self):
        drilled = estimate([ev(i, item="mesa", days=i * 0.01) for i in range(30)])
        diverse = estimate(distinct(6, sessions=2))
        assert drilled.independent_count == 30
        assert drilled.distinct_items == 1
        assert drilled.status == EvidenceStatus.INSUFFICIENT
        assert drilled.cefr is None
        # 30 repeats of one item carry less weight than 6 different items.
        assert drilled.effective_n < diverse.effective_n
        assert drilled.mastery < diverse.mastery

    def test_repetition_weight_is_bounded(self):
        weights = [
            estimate([ev(i, item="a", days=i) for i in range(n)]).effective_n for n in (1, 5, 50)
        ]
        assert weights[0] < weights[1] < weights[2] < 2 * weights[0] + 1e-9

    def test_latest_repeat_dominates(self):
        # Old successes, then a recent failure on the same item.
        rows = [ev(i, item="a", days=i) for i in range(5)]
        rows.append(ev(99, item="a", assessment="incorrect", days=10))
        e = estimate(rows, with_contributions=True)
        latest = next(c for c in e.contributions if c.event_id == rows[-1]["event_id"])
        assert latest.repetition == 1.0


class TestDifficulty:
    def test_success_on_hard_tasks_beats_success_on_easy(self):
        hard = estimate(distinct(6, difficulty=0.9))
        easy = estimate(distinct(6, difficulty=0.1))
        assert hard.mastery > easy.mastery

    def test_failure_on_easy_tasks_is_worse_than_failure_on_hard(self):
        easy = estimate(distinct(6, assessment="incorrect", difficulty=0.1))
        hard = estimate(distinct(6, assessment="incorrect", difficulty=0.9))
        assert easy.mastery < hard.mastery

    def test_unknown_difficulty_is_discounted_not_assumed_medium(self):
        unknown = estimate(distinct(6))
        known = estimate(distinct(6, difficulty=0.5))
        assert unknown.effective_n == pytest.approx(
            known.effective_n * DEFAULT_CONFIG.unknown_difficulty_discount
        )
        assert unknown.quality.known_difficulty_share == 0.0
        assert known.quality.known_difficulty_share == 1.0


class TestRecency:
    def test_recent_evidence_outweighs_old(self):
        improving = distinct(6, assessment="incorrect") + [
            ev(10 + i, item=f"new{i}", days=180) for i in range(6)
        ]
        declining = distinct(6) + [
            ev(10 + i, item=f"new{i}", assessment="incorrect", days=180) for i in range(6)
        ]
        assert estimate(improving).mastery > 0.5 > estimate(declining).mastery

    def test_recency_reference_is_the_evidence_not_the_clock(self):
        # Shifting every timestamp by a year changes nothing.
        rows = distinct(4) + [ev(9, item="z", assessment="incorrect", days=90)]
        shifted = [
            {
                **r,
                "created_at": (
                    datetime.fromisoformat(r["created_at"]) + timedelta(days=365)
                ).isoformat(),
            }
            for r in rows
        ]
        assert estimate(rows).mastery == pytest.approx(estimate(shifted).mastery)


class TestIndependenceAndDeterminism:
    def test_skills_are_estimated_independently(self):
        vocab = distinct(6, skill="vocabulary")
        alone = estimate(vocab, skill="vocabulary")
        with_grammar = estimate(
            vocab + distinct(8, skill="grammar", assessment="incorrect"), skill="vocabulary"
        )
        assert alone.mastery == pytest.approx(with_grammar.mastery)
        assert alone.status == with_grammar.status

    def test_order_independent(self):
        rows = distinct(10, sessions=3) + distinct(4, assessment="incorrect", difficulty=0.3)
        shuffled = list(rows)
        random.Random(7).shuffle(shuffled)
        a, b = estimate(rows), estimate(shuffled)
        assert a.mastery == b.mastery
        assert a.evidence_digest == b.evidence_digest
        assert a.baseline_mastery == b.baseline_mastery

    def test_fit_without_data_is_the_prior(self):
        theta, se = fit_ability([], prior_sd=1.5)
        assert theta == 0.0 and se == pytest.approx(1.5)


class TestUncertaintyAndStatus:
    def test_mastery_confidence_uncertainty_are_separate(self):
        e = estimate(distinct(5))
        assert e.mastery is not None
        assert 0.0 < e.uncertainty < 1.0
        assert 0.0 < e.evidence_index < 1.0
        assert e.mastery_low < e.mastery < e.mastery_high

    def test_more_independent_evidence_narrows_the_interval(self):
        assert estimate(distinct(12)).interval_width < estimate(distinct(4)).interval_width

    def test_status_progression(self):
        assert estimate(distinct(2)).status == EvidenceStatus.INSUFFICIENT
        assert estimate(distinct(4)).status == EvidenceStatus.PROVISIONAL
        # Many diverse items but one session: still provisional.
        assert estimate(distinct(20, difficulty=0.5)).status == EvidenceStatus.PROVISIONAL
        est = estimate(distinct(20, sessions=3, difficulty=0.5))
        assert est.status == EvidenceStatus.ESTIMATED
        assert est.cefr is not None

    def test_validated_requires_validated_instruments(self):
        rows = distinct(20, sessions=3, difficulty=0.5)
        assert estimate(rows).status == EvidenceStatus.ESTIMATED
        rows += [
            ev(100 + i, item=f"t{i}", task_type="standardized_test", difficulty=0.5)
            for i in range(2)
        ]
        assert estimate(rows).status == EvidenceStatus.VALIDATED

    def test_insufficient_has_no_band(self):
        e = estimate(distinct(2))
        assert e.mastery is not None  # a shrunk point estimate exists...
        assert e.cefr is None  # ...but no level is claimed

    def test_baseline_kept_for_comparison(self):
        rows = [{**ev(0, item="a"), "event_id": f"d{i}"} for i in range(8)]
        e = estimate(rows)
        # The legacy engine counts all 8 duplicates; v2 counts one.
        assert e.baseline_mastery is not None and e.baseline_mastery > e.mastery


class TestCoverage:
    def test_demonstrated_vs_practiced(self):
        rows = (
            distinct(3)
            + [ev(10 + i, item=f"bad{i}", assessment="incorrect") for i in range(2)]
            + [
                ev(20 + i, item=f"seen{i}", assessment="exposed", event_type="VOCAB_OBSERVED")
                for i in range(4)
            ]
        )
        cov = estimate(rows).coverage
        assert cov.practiced_items == 9
        assert cov.assessed_items == 5
        assert cov.demonstrated_items == 3
        assert cov.struggling_items == 2

    def test_repeats_do_not_inflate_coverage(self):
        cov = estimate([ev(i, item="mesa", days=i) for i in range(20)]).coverage
        assert cov.assessed_items == 1 and cov.demonstrated_items == 1

    def test_catalog_coverage(self):
        catalog = [("grammar.a", 0.1), ("grammar.b", 0.3), ("grammar.c", 0.6), ("grammar.d", None)]
        rows = [ev(1, item="a"), ev(2, item="b", assessment="incorrect")]
        cov = estimate(rows, catalogs={"grammar": catalog}).coverage
        assert cov.catalog_size == 4
        assert cov.catalog_assessed == 2
        assert cov.catalog_demonstrated == 1
        assert cov.unassessed_objectives == ["grammar.c", "grammar.d"]  # easiest first
        assert cov.catalog_assessed_fraction() == 0.5
