"""Phase 14 tests: the multi-signal difficulty controller."""

from __future__ import annotations

from src.agents import adaptive
from src.agents.difficulty_signals import (
    DifficultySignals,
    assess_difficulty,
    combine,
    extract_signals,
)


def _turns(*contents):
    return [{"role": "user", "content": c} for c in contents]


class TestExtractSignals:
    def test_empty_state(self):
        s = extract_signals({})
        assert s.turns == 0
        assert s.error_rate == 0.0

    def test_error_rate(self):
        state = {"grammar_errors": [{}, {}], "messages": _turns("hola", "adios")}
        assert extract_signals(state).error_rate == 1.0

    def test_lexical_diversity(self):
        # 4 tokens, all unique -> diversity 1.0.
        s = extract_signals({"messages": _turns("uno dos tres cuatro")})
        assert s.lexical_diversity == 1.0
        # Repeated words lower diversity.
        s2 = extract_signals({"messages": _turns("hola hola hola hola")})
        assert s2.lexical_diversity == 0.25

    def test_avg_response_length(self):
        s = extract_signals({"messages": _turns("una dos tres", "cuatro cinco")})
        assert s.avg_response_length == 2.5  # (3 + 2) / 2

    def test_repair_detection(self):
        s = extract_signals({"messages": _turns("no, perdón, quería decir sí", "vale")})
        assert s.repair_rate == 0.5  # 1 repair over 2 turns

    def test_as_dict(self):
        s = extract_signals({"messages": _turns("hola mundo")})
        d = s.as_dict()
        assert {"error_rate", "lexical_diversity", "avg_response_length", "repair_rate"} <= set(d)


class TestAssessDifficulty:
    def test_insufficient_evidence_appropriate(self):
        s = DifficultySignals(
            turns=1, error_rate=0.9, lexical_diversity=0.0, avg_response_length=1.0, repair_rate=1.0
        )
        assert assess_difficulty(s) == "appropriate"

    def test_struggling_is_too_hard(self):
        s = DifficultySignals(
            turns=4,
            error_rate=0.75,
            lexical_diversity=0.5,
            avg_response_length=2.0,
            repair_rate=0.5,
        )
        assert assess_difficulty(s) == "too_hard"

    def test_coping_is_too_easy(self):
        s = DifficultySignals(
            turns=4,
            error_rate=0.0,
            lexical_diversity=0.9,
            avg_response_length=14.0,
            repair_rate=0.0,
        )
        assert assess_difficulty(s) == "too_easy"

    def test_balanced_is_appropriate(self):
        s = DifficultySignals(
            turns=4, error_rate=0.2, lexical_diversity=0.5, avg_response_length=6.0, repair_rate=0.1
        )
        assert assess_difficulty(s) == "appropriate"


class TestCombine:
    def test_too_hard_wins(self):
        assert combine("appropriate", "too_hard") == "too_hard"
        assert combine("too_easy", "too_hard") == "too_hard"
        assert combine("too_hard", "appropriate") == "too_hard"

    def test_too_easy_when_no_difficulty(self):
        assert combine("too_easy", "appropriate") == "too_easy"
        assert combine("appropriate", "too_easy") == "too_easy"

    def test_appropriate_by_default(self):
        assert combine("appropriate", "appropriate") == "appropriate"


class TestAdaptiveNodeMultiSignal:
    def test_controller_can_force_too_hard(self):
        # Evaluator says appropriate, but the learner is clearly struggling.
        state = {
            "cefr_level": "B1",
            "current_scenario": {"persona": {"name": "Ana"}},
            "evaluation": {"difficulty_assessment": "appropriate"},
            "grammar_errors": [{}, {}, {}],
            "messages": _turns("no sé", "eh", "no", "vale"),
        }
        result = adaptive.adaptive_node(state)
        # The controller's too_hard verdict steps the level down.
        assert result["cefr_level"] == "A2"
        assert "difficulty_signals" in result["current_scenario"]

    def test_signals_attached_for_observability(self):
        state = {
            "cefr_level": "B1",
            "current_scenario": {},
            "evaluation": {"difficulty_assessment": "appropriate"},
            "messages": _turns("hola mundo"),
        }
        result = adaptive.adaptive_node(state)
        assert "difficulty_signals" in result["current_scenario"]
        assert "error_rate" in result["current_scenario"]["difficulty_signals"]
