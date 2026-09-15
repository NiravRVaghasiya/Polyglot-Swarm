"""Phase 13 tests: scenarios as pedagogical environments (target fields,
steering, success/failure evaluation)."""

from __future__ import annotations

from src.agents.conversation import _pedagogical_steering
from src.scenarios.engine import build_scenario_context, evaluate_success
from src.scenarios.loader import Scenario, get_scenario


def _scenario(**overrides) -> Scenario:
    base = {
        "id": "t_test",
        "title": "Test",
        "language": "es",
        "persona": {"name": "Ana", "role": "friend"},
        "objectives": [{"id": "o1", "description": "greet", "required_vocab": ["hola"]}],
    }
    base.update(overrides)
    return Scenario.model_validate(base)


class TestScenarioTargetFields:
    def test_defaults_empty(self):
        s = _scenario()
        assert s.target_grammar == []
        assert s.target_functions == []
        assert s.failure_conditions == []
        assert s.transfer_opportunities == []

    def test_parses_target_fields(self):
        s = _scenario(
            target_grammar=["ser_vs_estar"],
            target_functions=["make a request"],
            constraints=["stay in setting"],
            failure_conditions=["switched to English"],
            transfer_opportunities=["restaurante -> ristorante"],
        )
        assert s.target_grammar == ["ser_vs_estar"]
        assert s.target_functions == ["make a request"]
        assert s.failure_conditions == ["switched to English"]

    def test_all_target_vocabulary_unions_and_dedupes(self):
        s = _scenario(
            target_vocabulary=["hola", "mesa"],  # "hola" also in objective
        )
        vocab = s.all_target_vocabulary()
        assert vocab.count("hola") == 1  # deduped
        assert "mesa" in vocab

    def test_restaurant_scenario_has_targets(self):
        s = get_scenario("es_restaurant_ordering")
        assert s.target_grammar  # seeded
        assert s.target_functions
        assert s.failure_conditions
        assert s.transfer_opportunities

    def test_bar_scenario_has_targets(self):
        s = get_scenario("it_bar_caffe")
        assert s.target_grammar
        assert s.transfer_opportunities


class TestBuildContext:
    def test_context_exposes_targets(self):
        s = _scenario(target_grammar=["ser_vs_estar"], target_functions=["greet"])
        ctx = build_scenario_context(s, "A2")
        assert ctx["target_grammar"] == ["ser_vs_estar"]
        assert ctx["target_functions"] == ["greet"]
        assert "transfer_opportunities" in ctx

    def test_context_keeps_legacy_keys(self):
        ctx = build_scenario_context(_scenario(), "A2")
        for key in ("persona", "objectives", "location", "difficulty_guidance", "objective_specs"):
            assert key in ctx


class TestPedagogicalSteering:
    def test_empty_when_no_targets(self):
        # A scenario with no vocab/grammar/functions produces no steering block.
        assert _pedagogical_steering({}) == ""

    def test_includes_grammar_and_functions(self):
        ctx = {
            "target_grammar": ["ser_vs_estar"],
            "target_functions": ["make a request"],
            "target_vocabulary": ["mesa"],
        }
        block = _pedagogical_steering(ctx)
        assert "ser_vs_estar" in block
        assert "make a request" in block
        assert "mesa" in block

    def test_does_not_name_grammar_to_learner(self):
        block = _pedagogical_steering({"target_grammar": ["subjunctive"]})
        assert "do NOT name them" in block


class TestSuccessEvaluation:
    def test_passed_when_criteria_met(self):
        s = _scenario(objectives=[{"id": "o1", "description": "g", "required_vocab": ["hola"]}])
        out = evaluate_success(
            s, [{"role": "user", "content": "hola amigo"}], grammar_error_rate=0.0
        )
        assert out["objectives_completed"] is True
        assert out["passed"] is True
        assert out["failed"] is False

    def test_high_grammar_error_rate_fails_criteria(self):
        s = _scenario()
        out = evaluate_success(s, [{"role": "user", "content": "hola"}], grammar_error_rate=0.9)
        assert out["grammar_ok"] is False
        assert out["passed"] is False


class TestFailureConditions:
    def test_english_switch_detected(self):
        s = _scenario(failure_conditions=["switched to English"])
        english_turn = "yes please I want the thank you what where have"
        out = evaluate_success(s, [{"role": "user", "content": english_turn}])
        assert out["failed"] is True
        assert out["failure_reasons"]
        assert out["passed"] is False

    def test_spanish_turn_not_flagged_as_english(self):
        s = _scenario(failure_conditions=["switched to English"])
        out = evaluate_success(s, [{"role": "user", "content": "hola quiero una mesa"}])
        assert out["failed"] is False
