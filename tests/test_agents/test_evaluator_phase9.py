"""Phase 9 tests for evaluator_node's verifier upgrade (accept/revise/abstain),
preserving the legacy contract."""

from __future__ import annotations

from src.agents import evaluator
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


def _error(original, **extra):
    e = {
        "original": original,
        "correction": f"fixed {original}",
        "rule": "r",
        "explanation": "",
        "severity": "moderate",
    }
    e.update(extra)
    return e


def _state(**overrides):
    state = {
        "session_id": "s1",
        "user_id": "u1",
        "language": "Spanish",
        "cefr_level": "A2",
        "last_user_input": "Estoy bien.",
        "grammar_errors": [],
        "cultural_notes": [],
        "turn_count": 1,
    }
    state.update(overrides)
    return state


class TestVerifierDecisions:
    async def test_decisions_abstain_drops(self, monkeypatch):
        fake = FakeProvider(
            '{"overrides": [], "decisions": [{"index": 0, "decision": "abstain", '
            '"confidence": 0.3}], "adjustments": {}, "notes": []}'
        )
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)
        result = await evaluator.evaluator_node(_state(grammar_errors=[_error("a")]))
        assert result["grammar_errors"] == []
        assert result["evaluation"]["verifier"]["abstained"] == 1

    async def test_decisions_revise_applies(self, monkeypatch):
        fake = FakeProvider(
            '{"overrides": [], "decisions": [{"index": 0, "decision": "revise", '
            '"confidence": 0.9, "revised": "mejor"}], "adjustments": {}, "notes": []}'
        )
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)
        result = await evaluator.evaluator_node(_state(grammar_errors=[_error("a")]))
        assert len(result["grammar_errors"]) == 1
        assert result["grammar_errors"][0]["correction"] == "mejor"
        assert result["evaluation"]["verifier"]["revised"] == 1

    async def test_verifier_key_present(self, monkeypatch):
        fake = FakeProvider('{"overrides": [], "adjustments": {}, "notes": []}')
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)
        result = await evaluator.evaluator_node(_state(grammar_errors=[_error("a")]))
        assert "verifier" in result["evaluation"]
        assert "decisions" in result["evaluation"]["verifier"]

    async def test_legacy_overrides_still_work(self, monkeypatch):
        # The old protocol (index list) must still drop errors.
        fake = FakeProvider('{"overrides": [1], "adjustments": {}, "notes": []}')
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)
        result = await evaluator.evaluator_node(
            _state(grammar_errors=[_error("keep"), _error("drop")])
        )
        assert [e["original"] for e in result["grammar_errors"]] == ["keep"]
        assert result["evaluation"]["overrides"] == [1]

    async def test_low_confidence_error_suppressed_without_llm_decision(self, monkeypatch):
        # An error carrying its own low confidence (Phase 4) is abstained even
        # if the evaluator LLM offers no explicit decision.
        fake = FakeProvider('{"overrides": [], "adjustments": {}, "notes": []}')
        monkeypatch.setattr(evaluator, "get_provider", lambda tier: fake)
        result = await evaluator.evaluator_node(
            _state(grammar_errors=[_error("shaky", confidence=0.2)])
        )
        assert result["grammar_errors"] == []
