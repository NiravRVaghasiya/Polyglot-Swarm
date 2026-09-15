"""Tests for the scenario engine: context building, objective tracking, success."""

from __future__ import annotations

from src.scenarios import engine
from src.scenarios.loader import (
    Objective,
    Persona,
    Scenario,
    SuccessCriteria,
)


def _scenario():
    return Scenario(
        id="es_test",
        title="Ordering food",
        language="es",
        location="Madrid",
        persona=Persona(name="Carlos", role="waiter", personality="friendly"),
        objectives=[
            Objective(id="greet", description="Greet and sit", required_vocab=["mesa", "hola"]),
            Objective(id="order", description="Order food", required_vocab=["plato", "bebida"]),
        ],
        difficulty_scaling={
            "A2": "Speak slowly",
            "B2": "Fast speech with idioms",
        },
        opening_line="¡Buenas!",
        success_criteria=SuccessCriteria(
            all_objectives_completed=True,
            grammar_error_rate_max=0.2,
            target_vocabulary_used_min=0.6,
        ),
    )


def _msgs(*contents):
    return [{"role": "user", "content": c} for c in contents]


class TestBuildContext:
    def test_shape_matches_conversation_agent(self):
        ctx = engine.build_scenario_context(_scenario(), "A2")
        assert ctx["persona"]["name"] == "Carlos"
        assert ctx["persona"]["role"] == "waiter"
        assert isinstance(ctx["objectives"], list)
        assert all(isinstance(o, str) for o in ctx["objectives"])
        assert ctx["location"] == "Madrid"

    def test_difficulty_guidance_by_level(self):
        assert (
            engine.build_scenario_context(_scenario(), "A2")["difficulty_guidance"]
            == "Speak slowly"
        )
        assert "idioms" in engine.build_scenario_context(_scenario(), "B2")["difficulty_guidance"]

    def test_unknown_level_empty_guidance(self):
        assert engine.build_scenario_context(_scenario(), "C1")["difficulty_guidance"] == ""


class TestObjectiveStatus:
    def test_incomplete_when_vocab_missing(self):
        status = engine.objective_status(_scenario(), _msgs("hola"))
        greet = next(s for s in status if s["id"] == "greet")
        assert greet["completed"] is False  # "mesa" not yet used

    def test_complete_when_all_vocab_present(self):
        status = engine.objective_status(_scenario(), _msgs("hola, una mesa por favor"))
        greet = next(s for s in status if s["id"] == "greet")
        assert greet["completed"] is True

    def test_case_insensitive(self):
        status = engine.objective_status(_scenario(), _msgs("HOLA una MESA"))
        greet = next(s for s in status if s["id"] == "greet")
        assert greet["completed"] is True

    def test_no_messages_all_incomplete(self):
        status = engine.objective_status(_scenario(), [])
        assert all(s["completed"] is False for s in status)


class TestCoverage:
    def test_partial_coverage(self):
        # 2 of 4 required words used.
        coverage = engine.target_vocab_coverage(_scenario(), _msgs("hola mesa"))
        assert coverage == 0.5

    def test_full_coverage(self):
        coverage = engine.target_vocab_coverage(_scenario(), _msgs("hola mesa plato bebida"))
        assert coverage == 1.0


class TestEvaluateSuccess:
    def test_passes_when_all_met(self):
        result = engine.evaluate_success(
            _scenario(),
            _msgs("hola mesa", "plato bebida"),
            grammar_error_rate=0.1,
        )
        assert result["passed"] is True
        assert result["objectives_completed"] is True
        assert result["vocab_coverage"] == 1.0

    def test_fails_on_incomplete_objectives(self):
        result = engine.evaluate_success(_scenario(), _msgs("hola mesa"))
        assert result["objectives_completed"] is False
        assert result["passed"] is False

    def test_fails_on_high_grammar_error_rate(self):
        result = engine.evaluate_success(
            _scenario(),
            _msgs("hola mesa plato bebida"),
            grammar_error_rate=0.5,
        )
        assert result["grammar_ok"] is False
        assert result["passed"] is False
