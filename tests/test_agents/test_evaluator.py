"""Tests for the Evaluator Agent (QA layer)."""

from __future__ import annotations

from src.agents import evaluator
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls.append({"json_mode": json_mode})
        return self.reply


def _error(original, rule="r"):
    return {
        "original": original,
        "correction": f"fixed {original}",
        "rule": rule,
        "explanation": "",
        "severity": "moderate",
    }


def _state(**overrides):
    state = {
        "session_id": "s1",
        "user_id": "u1",
        "language": "Spanish",
        "cefr_level": "A2",
        "last_user_input": "Estoy bien, gracias.",
        "grammar_errors": [],
        "cultural_notes": [],
        "turn_count": 1,
    }
    state.update(overrides)
    return state


class TestOverrides:
    async def test_drops_false_positive(self, monkeypatch):
        fake = FakeProvider(
            '{"overrides": [1], "adjustments": {"difficulty": "appropriate"}, "notes": []}'
        )
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)

        state = _state(grammar_errors=[_error("real error"), _error("false positive")])
        result = await evaluator.evaluator_node(state)

        remaining = [e["original"] for e in result["grammar_errors"]]
        assert remaining == ["real error"]
        assert result["evaluation"]["grammar_errors_overridden"] == 1
        assert result["evaluation"]["overrides"] == [1]

    async def test_no_overrides_keeps_all(self, monkeypatch):
        fake = FakeProvider('{"overrides": [], "adjustments": {}, "notes": []}')
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)

        state = _state(grammar_errors=[_error("a"), _error("b")])
        result = await evaluator.evaluator_node(state)
        assert len(result["grammar_errors"]) == 2

    async def test_out_of_range_override_ignored(self, monkeypatch):
        fake = FakeProvider('{"overrides": [5, "x", -1], "adjustments": {}, "notes": []}')
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)

        state = _state(grammar_errors=[_error("a")])
        result = await evaluator.evaluator_node(state)
        assert len(result["grammar_errors"]) == 1
        assert result["evaluation"]["overrides"] == []


class TestConflictNotes:
    async def test_notes_passed_through(self, monkeypatch):
        fake = FakeProvider(
            '{"overrides": [], "adjustments": {"difficulty": "too_hard"}, '
            '"notes": ["Grammar wants formal but cultural note says informal is fine here."]}'
        )
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)

        state = _state(
            grammar_errors=[_error("a")],
            cultural_notes=["informal is fine with friends"],
        )
        result = await evaluator.evaluator_node(state)
        assert result["evaluation"]["difficulty_assessment"] == "too_hard"
        assert len(result["evaluation"]["notes"]) == 1


class TestFastPath:
    async def test_no_inputs_uses_heuristic(self, monkeypatch):
        def boom(tier):
            raise AssertionError("LLM should not be called with nothing to validate")

        monkeypatch.setattr(evaluator, "get_provider", boom)
        result = await evaluator.evaluator_node(_state(grammar_errors=[], cultural_notes=[]))
        assert result["evaluation"]["difficulty_assessment"] == "appropriate"
        assert result["grammar_errors"] == []

    async def test_llm_failure_keeps_errors(self, monkeypatch):
        class Boom(LLMProvider):
            name = "boom"

            def is_available(self):
                return True

            async def generate(self, *a, **k):
                raise RuntimeError("down")

        monkeypatch.setattr(evaluator, "get_provider", lambda tier: Boom())
        state = _state(grammar_errors=[_error("a")])
        result = await evaluator.evaluator_node(state)
        # On failure, no errors are dropped.
        assert len(result["grammar_errors"]) == 1


class TestHeuristicDifficulty:
    def test_zero_turns_appropriate(self):
        assert evaluator._assess_difficulty(_state(turn_count=0)) == "appropriate"

    def test_high_error_rate_too_hard(self):
        state = _state(grammar_errors=[_error(f"e{i}") for i in range(3)], turn_count=2)
        assert evaluator._assess_difficulty(state) == "too_hard"

    def test_low_error_rate_too_easy(self):
        state = _state(grammar_errors=[], turn_count=5)
        assert evaluator._assess_difficulty(state) == "too_easy"
