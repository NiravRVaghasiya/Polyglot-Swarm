"""lkm-subskill-v1: subskill estimates, patterns, predictions, leakage guard."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from src.adaptive.learner_model import (
    Pattern,
    SubskillModel,
    evidence_before,
    predict_from_rows,
    predict_success,
)
from src.learner.estimation import EvidenceMasteryEngine
from tests.test_adaptive.conftest import T0, grammar_row


def _mixed(days=(0, 3, 6)):
    rows = []
    for d in days:
        rows += [grammar_row("ser_vs_estar", True, day=d + i * 0.01) for i in range(4)]
        rows += [
            grammar_row("subjunctive_present", False, day=d + 0.1 + i * 0.01) for i in range(4)
        ]
    return rows


class TestSubskillEstimates:
    def test_skill_level_is_unchanged_from_v2(self):
        rows = _mixed()
        est = SubskillModel().estimate(rows)
        v2 = EvidenceMasteryEngine().estimate_all(rows)["grammar"]
        assert est.skills["grammar"].ability == v2.ability

    def test_subskills_separate_strong_and_weak_constructions(self):
        est = SubskillModel().estimate(_mixed())
        strong = est.subskills[("grammar", "ser_vs_estar")]
        weak = est.subskills[("grammar", "subjunctive_present")]
        assert strong.ability > est.skills["grammar"].ability > weak.ability
        # At the practised difficulty (0.25), not the 0.5 reference of `mastery`.
        assert strong.p_success(0.25)[0] > 0.8 and weak.p_success(0.25)[0] < 0.2
        assert strong.status == "estimated"

    def test_unseen_subskill_falls_back_to_skill_with_wider_uncertainty(self):
        est = SubskillModel().estimate(_mixed())
        unseen = est.subskill("grammar", "por_vs_para")
        skill = est.skills["grammar"]
        assert unseen.ability == skill.ability
        assert unseen.ability_se > skill.ability_se
        assert unseen.mastery is None

    def test_no_evidence_at_all_is_a_population_prior(self):
        pred = predict_from_rows([], "grammar", "ser_vs_estar", 0.25)
        assert pred.basis == "population_prior"
        assert pred.status == "insufficient_evidence"
        assert pred.p_low < 0.2 and pred.p_high > 0.8

    def test_correlated_judgments_count_once(self):
        rows = [
            grammar_row("ser_vs_estar", False, day=0, item="x", correlation="c1"),
            grammar_row("ser_vs_estar", False, day=0.001, item="x", correlation="c1"),
            grammar_row("ser_vs_estar", True, day=1, item="y"),
        ]
        est = SubskillModel().estimate(rows).subskills[("grammar", "ser_vs_estar")]
        assert est.independent_count == 2


class TestPatterns:
    def _history(self, bad_sessions: int):
        rows = []
        for s in range(4):
            rows += [grammar_row("ser_vs_estar", True, day=s * 2 + i * 0.01) for i in range(5)]
        for b in range(bad_sessions):
            day = 8 + b * 2
            rows += [grammar_row("ser_vs_estar", False, day=day + i * 0.01) for i in range(5)]
        return rows

    def test_one_bad_session_is_a_temporary_dip(self):
        est = SubskillModel().estimate(self._history(1)).subskills[("grammar", "ser_vs_estar")]
        assert est.pattern == Pattern.TEMPORARY_DIP
        assert est.recent_shift is not None and est.recent_shift < 0

    def test_two_bad_sessions_are_a_persistent_decline(self):
        est = SubskillModel().estimate(self._history(2)).subskills[("grammar", "ser_vs_estar")]
        assert est.pattern == Pattern.PERSISTENT_DECLINE

    def test_a_single_session_cannot_separate_dip_from_weakness(self):
        rows = [grammar_row("ser_vs_estar", False, day=i * 0.01) for i in range(6)]
        est = SubskillModel().estimate(rows).subskills[("grammar", "ser_vs_estar")]
        assert est.pattern == Pattern.SINGLE_SESSION

    def test_uniformly_weak_over_sessions_is_a_persistent_weakness(self):
        rows = []
        for s in range(3):
            rows += [grammar_row("ser_vs_estar", False, day=s * 2 + i * 0.01) for i in range(4)]
            rows.append(grammar_row("ser_vs_estar", True, day=s * 2 + 0.5))
        est = SubskillModel().estimate(rows).subskills[("grammar", "ser_vs_estar")]
        assert est.pattern == Pattern.PERSISTENT_WEAKNESS


class TestLeakage:
    def test_evidence_before_drops_rows_at_or_after_cutoff(self):
        rows = [grammar_row("ser_vs_estar", True, day=d) for d in (0, 1, 2)]
        cutoff = rows[1]["created_at"]
        assert [r["event_id"] for r in evidence_before(rows, cutoff)] == [rows[0]["event_id"]]

    def test_prediction_as_of_ignores_future_evidence(self):
        past = [grammar_row("ser_vs_estar", True, day=d * 0.1) for d in range(3)]
        future = [grammar_row("ser_vs_estar", False, day=10 + d * 0.1) for d in range(20)]
        as_of = (T0.replace(day=5)).isoformat()
        with_future = predict_from_rows(past + future, "grammar", "ser_vs_estar", 0.25, as_of=as_of)
        only_past = predict_from_rows(past, "grammar", "ser_vs_estar", 0.25, as_of=as_of)
        assert with_future == only_past
        assert with_future.kind == "prediction" and with_future.as_of == as_of


@settings(max_examples=40, deadline=None)
@given(
    outcomes=st.lists(st.booleans(), min_size=1, max_size=12),
    d1=st.floats(0.0, 1.0),
    d2=st.floats(0.0, 1.0),
    seed=st.integers(0, 1000),
)
def test_prediction_properties(outcomes, d1, d2, seed):
    rows = [
        grammar_row("ser_vs_estar", y, day=i * 0.5, difficulty=0.25 + 0.05 * (i % 3))
        for i, y in enumerate(outcomes)
    ]
    est = SubskillModel().estimate(rows)
    lo_d, hi_d = sorted((d1, d2))
    p_easy = predict_success(est, "grammar", "ser_vs_estar", lo_d)
    p_hard = predict_success(est, "grammar", "ser_vs_estar", hi_d)
    # Harder tasks are never predicted easier; intervals contain the estimate.
    assert p_hard.p_success <= p_easy.p_success + 1e-12
    assert p_easy.p_low <= p_easy.p_success <= p_easy.p_high
    # Order of the evidence does not matter (deterministic replay).
    shuffled = rows[:]
    random.Random(seed).shuffle(shuffled)
    again = predict_success(SubskillModel().estimate(shuffled), "grammar", "ser_vs_estar", lo_d)
    assert abs(again.p_success - p_easy.p_success) < 1e-9
    # Mastery probability falls as difficulty rises.
    sub = est.subskill("grammar", "ser_vs_estar")
    assert sub.mastery_probability(hi_d) <= sub.mastery_probability(lo_d) + 1e-12
