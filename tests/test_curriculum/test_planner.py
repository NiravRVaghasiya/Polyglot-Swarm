"""Phase 7 tests: the Next Best Learning Action planner, ELV scoring,
constraints, and difficulty."""

from __future__ import annotations

from src.curriculum import (
    ActionType,
    PlanConstraints,
    difficulty,
    objectives,
    plan_next_actions,
    plan_next_best,
)
from src.curriculum.constraints import GOAL_SKILL_WEIGHTS
from src.learner import get_knowledge_model
from src.memory import analytics, vocabulary_db


class TestDifficulty:
    def test_desirable_difficulty_peaks_in_middle(self):
        peak = difficulty.desirable_difficulty(0.6)
        assert peak > difficulty.desirable_difficulty(0.05)
        assert peak > difficulty.desirable_difficulty(0.98)

    def test_uncertainty_bonus_monotonic(self):
        assert difficulty.uncertainty_bonus(1.0) > difficulty.uncertainty_bonus(0.0)

    def test_difficulty_appropriate_when_fatigued(self):
        assert not difficulty.difficulty_appropriate(0.2, fatigue=0.8)
        assert difficulty.difficulty_appropriate(0.6, fatigue=0.8)
        assert not difficulty.difficulty_appropriate(0.99)


class TestConstraints:
    def test_goal_weights_boost_target_skills(self):
        c = PlanConstraints(goal="reading")
        assert c.skill_weight("reading") > 1.0
        assert c.skill_weight("speaking") == 1.0

    def test_unknown_goal_no_boost(self):
        c = PlanConstraints(goal="mystery")
        assert c.skill_weight("speaking") == 1.0

    def test_fatigue_penalizes_long_actions(self):
        c = PlanConstraints(fatigue=0.8)
        assert c.fatigue_penalty(10.0) < c.fatigue_penalty(1.0)
        assert PlanConstraints(fatigue=0.0).fatigue_penalty(10.0) == 1.0

    def test_all_goals_have_valid_skill_weights(self):
        for weights in GOAL_SKILL_WEIGHTS.values():
            assert all(v > 0 for v in weights.values())


class TestELV:
    def test_elv_in_range(self):
        v = objectives.expected_learning_value(
            mastery=0.5,
            uncertainty=0.5,
            urgency=0.5,
            skill="grammar",
            estimated_minutes=5,
            constraints=PlanConstraints(),
        )
        assert 0.0 <= v <= 1.0

    def test_goal_weight_raises_elv(self):
        base = objectives.expected_learning_value(
            mastery=0.5,
            uncertainty=0.5,
            urgency=0.5,
            skill="reading",
            estimated_minutes=5,
            constraints=PlanConstraints(goal="conversational"),
        )
        boosted = objectives.expected_learning_value(
            mastery=0.5,
            uncertainty=0.5,
            urgency=0.5,
            skill="reading",
            estimated_minutes=5,
            constraints=PlanConstraints(goal="reading"),
        )
        assert boosted >= base

    def test_review_urgency_most_overdue_first(self):
        assert objectives.review_urgency(0, 5) > objectives.review_urgency(4, 5)
        assert objectives.review_urgency(0, 0) == 0.0

    def test_weakness_urgency(self):
        assert objectives.weakness_urgency(10, 10) > objectives.weakness_urgency(1, 10)


class TestPlanner:
    def test_empty_learner_gets_conversation_fallback(self, temp_storage):
        plan = plan_next_actions("newbie", "Spanish")
        assert plan  # never empty
        assert any(a.type == ActionType.CONTINUE_CONVERSATION for a in plan)

    def test_due_review_surfaces(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa", next_review="2020-01-01T00:00:00+00:00")
        plan = plan_next_actions("u1", "Spanish")
        review = [a for a in plan if a.type == ActionType.REVIEW_VOCAB]
        assert any(a.target == "mesa" for a in review)

    def test_grammar_weakness_surfaces(self, temp_storage):
        for _ in range(3):
            analytics.record_error("u1", "Spanish", "ser_vs_estar")
        plan = plan_next_actions("u1", "Spanish")
        grammar = [a for a in plan if a.skill == "grammar"]
        assert any(a.target == "ser_vs_estar" for a in grammar)

    def test_vs_construction_becomes_contrast(self, temp_storage):
        analytics.record_error("u1", "Spanish", "por_vs_para")
        plan = plan_next_actions("u1", "Spanish")
        contrast = [a for a in plan if a.target == "por_vs_para"]
        assert contrast and contrast[0].type == ActionType.CONTRAST_TWO_FORMS

    def test_plan_respects_time_budget(self, temp_storage):
        for i in range(10):
            vocabulary_db.upsert_word(
                "u1", "Spanish", f"w{i}", next_review="2020-01-01T00:00:00+00:00"
            )
        plan = plan_next_actions(
            "u1", "Spanish", constraints=PlanConstraints(time_available_minutes=3, max_actions=10)
        )
        # First action always allowed; subsequent ones must fit the budget.
        total = sum(a.estimated_minutes for a in plan[1:])
        assert total <= 3

    def test_plan_ranked_by_priority(self, temp_storage):
        for _ in range(5):
            analytics.record_error("u1", "Spanish", "ser_vs_estar")
        plan = plan_next_actions("u1", "Spanish")
        priorities = [a.priority for a in plan]
        assert priorities == sorted(priorities, reverse=True)

    def test_max_actions_respected(self, temp_storage):
        for _ in range(3):
            analytics.record_error("u1", "Spanish", "gender_agreement")
        plan = plan_next_actions("u1", "Spanish", constraints=PlanConstraints(max_actions=2))
        assert len(plan) <= 2

    def test_plan_next_best_returns_top(self, temp_storage):
        get_knowledge_model().update_from_events(
            "u1", "Spanish", [{"skill": "grammar", "assessment": "incorrect", "confidence": 0.9}]
        )
        best = plan_next_best("u1", "Spanish")
        assert best is not None
        assert best.priority >= 0.0

    def test_action_as_dict(self, temp_storage):
        best = plan_next_best("newbie", "Spanish")
        d = best.as_dict()
        assert {"type", "target", "skill", "reason", "priority"} <= set(d)


class TestPlanCLI:
    def test_plan_command_runs(self, temp_storage):
        from typer.testing import CliRunner

        from src.cli import app

        vocabulary_db.upsert_word(
            "cli-user", "Spanish", "mesa", next_review="2020-01-01T00:00:00+00:00"
        )
        result = CliRunner().invoke(app, ["plan", "--language", "Spanish"])
        assert result.exit_code == 0
        assert "plan" in result.stdout.lower()
