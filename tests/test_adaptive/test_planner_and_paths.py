"""Next-best-action engine and personalized learning paths."""

from __future__ import annotations

import random
from datetime import timedelta

from fsrs import Card, Rating, Scheduler

from src.adaptive.paths import build_path
from src.adaptive.planner import (
    MAX_ASSESSMENTS,
    PlannerConfig,
    Recommendation,
    _dedupe,
    plan,
)
from src.curriculum.constraints import PlanConstraints
from tests.test_adaptive.conftest import T0, grammar_row, snapshot, vocab_row

REQUIRED = (
    "activity",
    "intent",
    "skill",
    "objective_id",
    "difficulty",
    "rationale",
    "expected_benefit",
    "evidence",
    "uncertainty",
    "score",
    "components",
)
WIDE = PlanConstraints(time_available_minutes=60, max_actions=12)


def _keys(p):
    return [(r.activity, r.intent, r.target) for r in p.recommendations]


def _strong(construction, sessions=4, start=0.0):
    rows = []
    for s in range(sessions):
        rows += [
            grammar_row(construction, True, day=start + s * 2 + i * 0.01, difficulty=0.25)
            for i in range(5)
        ]
    return rows


def _weak(construction, sessions=3, start=0.0, difficulty=0.25):
    rows = []
    for s in range(sessions):
        day = start + s * 2
        rows += [
            grammar_row(construction, False, day=day + i * 0.01, difficulty=difficulty)
            for i in range(4)
        ]
        rows.append(grammar_row(construction, True, day=day + 0.5, difficulty=difficulty))
    return rows


def _due_card(word, *, reviewed=True):
    sched = Scheduler()
    card = Card(due=T0)
    if reviewed:
        card, _ = sched.review_card(card, Rating.Good, T0 - timedelta(days=20))
        card.due = T0
    return {"word": word, "card_state": card.to_dict(), "next_review": T0.isoformat()}


class TestNextBestAction:
    def test_new_learner_gets_assessment_not_remediation(self):
        p = plan(snapshot([], day=0))
        intents = [r.intent for r in p.recommendations]
        assert "remediation" not in intents
        assert 1 <= intents.count("assessment") <= MAX_ASSESSMENTS
        assert any(r.activity == "conversation_practice" for r in p.recommendations)

    def test_demonstrated_weakness_is_remediated_with_evidence(self):
        rows = _strong("gender_agreement") + _weak("ser_vs_estar", start=0.3)
        p = plan(snapshot(rows, day=8), constraints=WIDE)
        rec = next(r for r in p.recommendations if r.target == "ser_vs_estar")
        assert rec.intent == "remediation" and rec.activity == "grammar_practice"
        assert rec.evidence["event_count"] > 0 and rec.evidence["event_ids"]
        assert rec.difficulty is not None and rec.difficulty.task_tier == "scaffolded"
        d = rec.as_dict()
        assert all(d[k] is not None for k in REQUIRED)
        assert d["predicted_success"]["kind"] == "prediction"

    def test_probing_never_crowds_out_remediation(self):
        # Regression: two never-assessed skills used to fill a 15-minute
        # session and push an estimated, persistent weakness out of it.
        rows = _weak("ser_vs_estar", sessions=3)
        p = plan(snapshot(rows, day=7), constraints=PlanConstraints(time_available_minutes=15))
        probing = sum(
            r.estimated_minutes
            for r in p.recommendations
            if r.intent == "assessment" and r.evidence.get("check") != "dip_confirmation"
        )
        assert probing <= 0.4 * 15
        assert any(
            r.target == "ser_vs_estar" and r.intent == "remediation" for r in p.recommendations
        )

    def test_temporary_dip_triggers_assessment_not_remediation(self):
        rows = _strong("ser_vs_estar", sessions=4)
        rows += [grammar_row("ser_vs_estar", False, day=8 + i * 0.01) for i in range(5)]
        p = plan(snapshot(rows, day=9), constraints=WIDE)
        rec = next(r for r in p.recommendations if r.target == "ser_vs_estar")
        assert rec.intent == "assessment"
        assert "fluctuation" in " ".join(rec.rationale)

    def test_mastered_material_is_not_repeated_without_a_retention_reason(self):
        rows = _strong("gender_agreement", sessions=5)
        fresh = plan(snapshot(rows, day=9), constraints=WIDE)
        # Mastered even at the most demanding task this content allows: no
        # practice at all; the engine moves on to the next construction.
        assert not [r for r in fresh.recommendations if r.target == "gender_agreement"]
        assert any(r.intent == "introduction" for r in fresh.recommendations)
        stale = plan(snapshot(rows, day=400), constraints=WIDE)
        rec = next(r for r in stale.recommendations if r.target == "gender_agreement")
        assert rec.intent == "review" and rec.activity == "retention_review"

    def test_weak_prerequisite_comes_first(self):
        rows = _weak("gender_agreement", difficulty=1 / 12)
        rows += [
            grammar_row("preterite_vs_imperfect", False, day=5 + i * 0.01, difficulty=5 / 12)
            for i in range(3)
        ]
        p = plan(snapshot(rows, day=7), constraints=WIDE)
        targets = {r.target: r for r in p.recommendations}
        assert targets["gender_agreement"].intent == "remediation"
        assert "prerequisite of grammar.preterite_vs_imperfect" in " ".join(
            targets["gender_agreement"].rationale
        )
        assert "preterite_vs_imperfect" not in targets

    def test_reviews_progress_from_recognition_to_production(self):
        vocab = [_due_card("mesa"), _due_card("silla")]
        rows = [vocab_row("mesa", day=-5, assessment="correct")]
        p = plan(snapshot(rows, day=0, vocabulary=vocab), constraints=WIDE)
        modes = {r.target: r.mode for r in p.recommendations if r.activity == "vocabulary_review"}
        assert modes == {"mesa": "production", "silla": "recognition"}

    def test_never_recalled_word_is_flagged_as_exposure_only(self):
        vocab = [_due_card("mesa", reviewed=False)]
        rows = [vocab_row("mesa", day=-1, assessment="exposed", event_type="VOCAB_OBSERVED")]
        p = plan(snapshot(rows, day=0, vocabulary=vocab), constraints=WIDE)
        rec = next(r for r in p.recommendations if r.target == "mesa")
        assert "exposure is not recall" in " ".join(rec.rationale)

    def test_leech_is_remediated_instead_of_reviewed(self):
        vocab = [_due_card("mesa")]
        rows = [vocab_row("mesa", day=-9, assessment="correct", mode="production")]
        rows += [
            vocab_row("mesa", day=-d, assessment="incorrect", mode="production") for d in (6, 4, 2)
        ]
        p = plan(snapshot(rows, day=0, vocabulary=vocab), constraints=WIDE)
        recs = [r for r in p.recommendations if r.target == "mesa"]
        assert [r.activity for r in recs] == ["vocabulary_remediation"]

    def test_dedupe_keeps_one_per_item_and_both_reasons(self):
        a = Recommendation(
            "grammar_practice",
            "reinforcement",
            "vocabulary",
            "mesa",
            objective_id="vocabulary.mesa",
            rationale=["practice"],
            score=0.9,
            sources=["curriculum"],
        )
        b = Recommendation(
            "vocabulary_review",
            "review",
            "vocabulary",
            "mesa",
            objective_id="vocabulary.mesa",
            rationale=["due"],
            score=0.5,
            sources=["fsrs"],
        )
        (only,) = _dedupe([a, b])
        assert only.activity == "vocabulary_review"
        assert only.sources == ["curriculum", "fsrs"] and len(only.rationale) == 2

    def test_plan_is_deterministic_and_order_independent(self):
        rows = _strong("gender_agreement") + _weak("ser_vs_estar", start=0.3)
        shuffled = rows[:]
        random.Random(3).shuffle(shuffled)
        a = plan(snapshot(rows, day=8)).as_dict()
        b = plan(snapshot(shuffled, day=8)).as_dict()
        assert a == b and a["input_digest"] == b["input_digest"]

    def test_ablation_configs_run(self):
        rows = _strong("gender_agreement") + _weak("ser_vs_estar", start=0.3)
        for cfg in (
            PlannerConfig(predictive=False, adaptive_difficulty=False, fsrs_integration=False),
            PlannerConfig(fsrs_integration=False),
        ):
            assert plan(snapshot(rows, day=8), config=cfg).recommendations


class TestLearningPath:
    def test_states_gaps_and_short_term(self):
        rows = _strong("ser_vs_estar") + _weak("gender_agreement", start=0.3, difficulty=1 / 12)
        path = build_path(snapshot(rows, day=8, target_cefr="B1"))
        states = {s.objective_id: s.state for s in path.steps}
        assert states["grammar.gender_agreement"] == "weak"
        assert states["grammar.ser_vs_estar"] == "mastered"
        assert states["grammar.preterite_vs_imperfect"] == "blocked"
        assert path.prerequisite_gaps == [
            {
                "objective_id": "grammar.preterite_vs_imperfect",
                "blocked_by": ["grammar.gender_agreement"],
            }
        ]
        assert path.short_term[0] == "grammar.gender_agreement"
        assert "grammar.ser_vs_estar" not in path.short_term  # mastered: not repeated
        assert "grammar.subjunctive_present" not in path.long_term  # beyond target B1
        assert path.recurrent_errors[0]["objective_id"] == "grammar.gender_agreement"

    def test_prerequisites_are_ordered_first(self):
        path = build_path(snapshot([], day=0))
        order = [s.objective_id for s in path.steps]
        assert order.index("grammar.gender_agreement") < order.index(
            "grammar.preterite_vs_imperfect"
        )
        assert order.index("grammar.ser_vs_estar") < order.index("grammar.subjunctive_present")

    def test_changes_are_explained_against_the_previous_path(self):
        rows = _weak("ser_vs_estar")
        first = build_path(snapshot(rows, day=6)).as_dict()
        rows += _strong("ser_vs_estar", sessions=6, start=10)
        second = build_path(snapshot(rows, day=22, previous_path=first))
        change = next(c for c in second.changes if c["objective_id"] == "grammar.ser_vs_estar")
        assert change["from"] == "weak" and change["to"] in ("in_progress", "mastered")
        assert change["evidence_count_after"] > change["evidence_count_before"]
