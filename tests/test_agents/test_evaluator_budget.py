"""Phase 22 tests: budget-aware tier escalation in the evaluator.

The evaluator uses the cheap "fast" tier by default, but escalates to
"primary" when a candidate grammar error is high-impact (per
src.evaluation.policies.is_high_impact) — a confident, non-trivial
correction is exactly the case where a false positive is most costly, so
it's worth the stronger tier's judgment.
"""

from __future__ import annotations

from src.agents import evaluator
from src.llm.provider import LLMProvider


class RecordingProvider(LLMProvider):
    name = "recording"

    def __init__(self, reply: str = '{"overrides": [], "adjustments": {}, "notes": []}'):
        self.reply = reply

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


def _error(classification="wrong", severity="moderate", **overrides):
    error = {
        "original": "x",
        "correction": "fixed x",
        "rule": "r",
        "explanation": "",
        "classification": classification,
        "severity": severity,
    }
    error.update(overrides)
    return error


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


class TestBudgetAwareTierSelection:
    async def test_high_impact_correction_escalates_to_primary(self, monkeypatch):
        captured = {}

        def fake_get_provider(tier):
            captured["tier"] = tier
            return RecordingProvider()

        monkeypatch.setattr(evaluator, "get_provider", fake_get_provider)

        state = _state(grammar_errors=[_error(classification="wrong", severity="critical")])
        await evaluator.evaluator_node(state)

        assert captured["tier"] == "primary"

    async def test_low_impact_correction_stays_on_fast_tier(self, monkeypatch):
        captured = {}

        def fake_get_provider(tier):
            captured["tier"] = tier
            return RecordingProvider()

        monkeypatch.setattr(evaluator, "get_provider", fake_get_provider)

        # "acceptable" is not a genuine-error classification and "minor"
        # severity is below the high-impact bar (see policies.is_high_impact).
        state = _state(grammar_errors=[_error(classification="acceptable", severity="minor")])
        await evaluator.evaluator_node(state)

        assert captured["tier"] == "fast"

    async def test_moderate_severity_wrong_classification_escalates(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            evaluator,
            "get_provider",
            lambda tier: (captured.setdefault("tier", tier), RecordingProvider())[1],
        )

        state = _state(grammar_errors=[_error(classification="wrong", severity="moderate")])
        await evaluator.evaluator_node(state)

        assert captured["tier"] == "primary"

    async def test_mixed_errors_escalate_if_any_is_high_impact(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            evaluator,
            "get_provider",
            lambda tier: (captured.setdefault("tier", tier), RecordingProvider())[1],
        )

        state = _state(
            grammar_errors=[
                _error(classification="informal", severity="minor"),
                _error(classification="wrong", severity="critical"),
            ]
        )
        await evaluator.evaluator_node(state)

        assert captured["tier"] == "primary"

    async def test_no_grammar_errors_but_cultural_notes_stays_on_fast_tier(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            evaluator,
            "get_provider",
            lambda tier: (captured.setdefault("tier", tier), RecordingProvider())[1],
        )

        state = _state(grammar_errors=[], cultural_notes=["some note"])
        await evaluator.evaluator_node(state)

        assert captured["tier"] == "fast"
