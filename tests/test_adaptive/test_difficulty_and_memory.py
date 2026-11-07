"""Adaptive difficulty and FSRS memory replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from src.adaptive.difficulty import (
    MAX_STEP_DOWN,
    MAX_STEP_UP,
    TASK_WINDOW,
    choose_difficulty,
    performance_curve,
)
from src.adaptive.learner_model import Pattern, SubskillEstimate
from src.adaptive.memory import live_retrievability, rating_for, replay_memory
from src.agents.srs import FIRST_RETRIEVAL_DELAY, schedule_new_items
from tests.test_adaptive.conftest import T0, grammar_row, vocab_row


def _est(ability=0.0, se=0.3, status="estimated", pattern=Pattern.STABLE):
    return SubskillEstimate(
        skill="grammar",
        subskill="x",
        objective_id="grammar.x",
        ability=ability,
        ability_se=se,
        status=status,
        pattern=pattern,
        independent_count=10,
    )


class TestDifficulty:
    def test_no_evidence_uses_the_content_level(self):
        d = choose_difficulty(
            _est(status="insufficient_evidence"), objective_id="grammar.x", content_difficulty=0.25
        )
        assert d.task_difficulty == 0.25 and d.task_tier == "standard"
        assert d.linguistic_level == "A2"

    def test_competence_raises_difficulty_gradually(self):
        d = choose_difficulty(
            _est(ability=3.0),
            objective_id="grammar.x",
            content_difficulty=0.5,
            previous_difficulty=0.45,
        )
        assert d.task_difficulty == 0.45 + MAX_STEP_UP
        assert d.bounded_by == "max_step_up"

    def test_isolated_bad_session_holds_difficulty(self):
        d = choose_difficulty(
            _est(ability=-2.0, pattern=Pattern.TEMPORARY_DIP),
            objective_id="grammar.x",
            content_difficulty=0.5,
            previous_difficulty=0.5,
        )
        assert d.task_difficulty == 0.5 and d.bounded_by == "temporary_dip_hold"

    def test_persistent_weakness_lowers_difficulty_bounded(self):
        d = choose_difficulty(
            _est(ability=-3.0, pattern=Pattern.PERSISTENT_WEAKNESS),
            objective_id="grammar.x",
            content_difficulty=0.5,
            previous_difficulty=0.5,
        )
        assert d.task_difficulty == 0.5 - MAX_STEP_DOWN

    def test_content_window_keeps_linguistic_level(self):
        d = choose_difficulty(
            _est(ability=-6.0, pattern=Pattern.PERSISTENT_WEAKNESS),
            objective_id="grammar.x",
            content_difficulty=0.6,
            linguistic_level="B2",
        )
        assert d.task_difficulty == 0.6 - TASK_WINDOW
        assert d.linguistic_level == "B2" and d.task_tier == "scaffolded"
        assert d.bounded_by == "content_window_low"

    def test_uncertainty_makes_the_choice_easier(self):
        sure = choose_difficulty(
            _est(ability=1.0, se=0.1), objective_id="g", content_difficulty=0.5
        )
        unsure = choose_difficulty(
            _est(ability=1.0, se=1.2), objective_id="g", content_difficulty=0.5
        )
        assert unsure.task_difficulty <= sure.task_difficulty

    def test_performance_curve_is_monotone(self):
        curve = performance_curve(_est(ability=0.5))
        ps = [pt["p_success"] for pt in curve]
        assert ps == sorted(ps, reverse=True) and len(curve) == 6


@settings(max_examples=80, deadline=None)
@given(
    ability=st.floats(-6, 6),
    se=st.floats(0.05, 2.0),
    content=st.floats(0.0, 1.0),
    previous=st.one_of(st.none(), st.floats(0.0, 1.0)),
    pattern=st.sampled_from(
        [Pattern.STABLE, Pattern.TEMPORARY_DIP, Pattern.PERSISTENT_WEAKNESS, Pattern.IMPROVING]
    ),
    status=st.sampled_from(["insufficient_evidence", "provisional", "estimated"]),
)
def test_difficulty_is_bounded_and_explained(ability, se, content, previous, pattern, status):
    d = choose_difficulty(
        _est(ability, se, status, pattern),
        objective_id="g",
        content_difficulty=content,
        previous_difficulty=previous,
    )
    assert 0.0 <= d.task_difficulty <= 1.0
    assert content - TASK_WINDOW - 1e-9 <= d.task_difficulty <= content + TASK_WINDOW + 1e-9
    if previous is not None and d.bounded_by not in ("content_window_low", "content_window_high"):
        assert -MAX_STEP_DOWN - 1e-9 <= d.step <= MAX_STEP_UP + 1e-9
        if pattern == Pattern.TEMPORARY_DIP:
            assert d.step >= -1e-9  # a one-session dip never lowers difficulty
    assert d.reason


class TestMemory:
    def test_exposure_is_not_recall(self):
        rows = [vocab_row("mesa", day=0, assessment="exposed", event_type="VOCAB_OBSERVED")]
        state = replay_memory(rows, T0 + timedelta(days=1))["vocabulary:mesa"]
        assert state.exposures == 1 and state.reviews == 0
        assert not state.demonstrated and state.retrievability is None

    def test_recognition_is_weaker_than_production(self):
        now = T0 + timedelta(days=5)
        rec = replay_memory([vocab_row("mesa", day=0, assessment="correct")], now)
        prod = replay_memory(
            [vocab_row("mesa", day=0, assessment="correct", mode="production")], now
        )
        assert rec["vocabulary:mesa"].recognition_successes == 1
        assert prod["vocabulary:mesa"].production_successes == 1
        assert rec["vocabulary:mesa"].retrievability < prod["vocabulary:mesa"].retrievability
        assert rating_for("recognition", True, 4).name == "Hard"
        assert rating_for("production", True, 4).name == "Easy"
        assert rating_for("production", False, 4).name == "Again"

    def test_repeated_failures_make_a_leech(self):
        rows = [vocab_row("mesa", day=0, assessment="correct", mode="production")]
        rows += [
            vocab_row("mesa", day=d, assessment="incorrect", mode="production") for d in (1, 2, 3)
        ]
        state = replay_memory(rows, T0 + timedelta(days=4))["vocabulary:mesa"]
        assert state.consecutive_failures == 3 and state.lapses == 3 and state.leech

    def test_correlated_duplicates_and_future_rows_are_ignored(self):
        rows = [
            grammar_row("ser_vs_estar", True, day=0, correlation="c"),
            grammar_row("ser_vs_estar", True, day=0.001, correlation="c"),
            grammar_row("ser_vs_estar", False, day=9),
        ]
        state = replay_memory(rows, T0 + timedelta(days=1))["grammar.ser_vs_estar"]
        assert state.reviews == 1 and state.successes == 1

    def test_new_words_get_unreviewed_cards(self):
        before = datetime.now(UTC)
        item = schedule_new_items([{"word": "mesa"}])[0]
        card = item["card_state"]
        assert card["last_review"] is None and card["stability"] is None
        due = datetime.fromisoformat(item["next_review"])
        assert before + FIRST_RETRIEVAL_DELAY - timedelta(seconds=5) <= due
        assert live_retrievability(card, due) is None
