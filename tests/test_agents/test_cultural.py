"""Tests for the Cultural Context Agent."""

from __future__ import annotations

import pytest

from src.agents import cultural
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return self.reply


def _state(**overrides):
    state = {
        "session_id": "s1",
        "user_id": "u1",
        "language": "Spanish",
        "mode": "conversation",
        "messages": [],
        "current_scenario": {
            "persona": {"name": "Sr. García", "role": "landlord"},
            "location": "Madrid",
            "context": "renting an apartment",
        },
        "cultural_notes": [],
        "cefr_level": "A2",
        "last_user_input": "Oye tío, ¿cuánto es el alquiler?",
    }
    state.update(overrides)
    return state


@pytest.fixture(autouse=True)
def _no_persist(monkeypatch):
    """Stub out vector-store persistence so tests stay offline."""
    persisted = {}

    def fake_persist(state, notes):
        persisted["notes"] = notes

    monkeypatch.setattr(cultural, "_persist_notes", fake_persist)
    return persisted


class TestCulturalNode:
    async def test_uses_fast_tier_json_mode(self, monkeypatch):
        fake = FakeProvider('{"notes": []}')
        captured = {}
        monkeypatch.setattr(
            cultural,
            "get_provider",
            lambda tier: captured.update(tier=tier) or fake,
        )
        await cultural.cultural_node(_state())
        assert captured["tier"] == "fast"
        assert fake.calls[0]["json_mode"] is True

    async def test_appends_note_text(self, monkeypatch):
        payload = (
            '{"notes": [{"note": "Using \'tío\' is very informal for a landlord; '
            'prefer usted.", "category": "register", "severity": "important"}]}'
        )
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state())
        assert len(result["cultural_notes"]) == 1
        assert "usted" in result["cultural_notes"][0]

    async def test_persists_structured_notes(self, monkeypatch, _no_persist):
        payload = '{"notes": [{"note": "n", "category": "custom", "severity": "info"}]}'
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        await cultural.cultural_node(_state())
        assert _no_persist["notes"][0]["category"] == "custom"

    async def test_low_confidence_note_is_dropped(self, monkeypatch, _no_persist):
        # Phase 20: a fabricated/uncertain cultural claim must not surface as
        # an asserted fact — below ABSTAIN_THRESHOLD (0.5) it is suppressed,
        # mirroring how grammar corrections abstain.
        payload = (
            '{"notes": [{"note": "dubious claim", "category": "custom", '
            '"severity": "info", "confidence": 0.2}]}'
        )
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state())
        assert result["cultural_notes"] == []
        assert "notes" not in _no_persist  # never reached persistence either

    async def test_high_confidence_note_is_kept(self, monkeypatch):
        payload = (
            '{"notes": [{"note": "solid claim", "category": "custom", '
            '"severity": "info", "confidence": 0.9}]}'
        )
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state())
        assert result["cultural_notes"] == ["solid claim"]

    async def test_confidence_exactly_at_threshold_is_kept(self, monkeypatch):
        from src.evaluation.policies import ABSTAIN_THRESHOLD

        payload = (
            f'{{"notes": [{{"note": "borderline", "category": "custom", '
            f'"severity": "info", "confidence": {ABSTAIN_THRESHOLD}}}]}}'
        )
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state())
        assert result["cultural_notes"] == ["borderline"]

    async def test_mixed_confidence_keeps_only_confident_notes(self, monkeypatch):
        payload = (
            '{"notes": ['
            '{"note": "keep me", "category": "custom", "severity": "info", "confidence": 0.95},'
            '{"note": "drop me", "category": "custom", "severity": "info", "confidence": 0.1}'
            "]}"
        )
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state())
        assert result["cultural_notes"] == ["keep me"]

    async def test_missing_confidence_defaults_to_fully_confident(self, monkeypatch):
        # Backward-compat: a response with no "confidence" key (as every
        # pre-Phase-20 test payload has) must not be silently dropped.
        payload = '{"notes": [{"note": "legacy note", "category": "custom", "severity": "info"}]}'
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state())
        assert result["cultural_notes"] == ["legacy note"]

    async def test_preserves_existing_notes(self, monkeypatch):
        payload = '{"notes": [{"note": "new note", "category": "idiom", "severity": "info"}]}'
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider(payload))
        result = await cultural.cultural_node(_state(cultural_notes=["old note"]))
        assert result["cultural_notes"] == ["old note", "new note"]

    async def test_empty_notes_no_change(self, monkeypatch):
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider('{"notes": []}'))
        result = await cultural.cultural_node(_state(cultural_notes=["keep"]))
        assert result["cultural_notes"] == ["keep"]

    async def test_short_input_skipped(self, monkeypatch):
        def boom(tier):
            raise AssertionError("provider should not be called for short input")

        monkeypatch.setattr(cultural, "get_provider", boom)
        result = await cultural.cultural_node(_state(last_user_input="ok"))
        assert result["cultural_notes"] == []

    async def test_malformed_json_yields_no_notes(self, monkeypatch):
        monkeypatch.setattr(cultural, "get_provider", lambda tier: FakeProvider("not json"))
        result = await cultural.cultural_node(_state())
        assert result["cultural_notes"] == []


class TestParsing:
    def test_strips_code_fence(self):
        fenced = '```json\n{"notes": [{"note": "x", "category": "idiom", "severity": "info"}]}\n```'
        notes = cultural._parse_cultural_response(fenced)
        assert notes[0]["note"] == "x"

    def test_skips_empty_note(self):
        notes = cultural._parse_cultural_response('{"notes": [{"note": ""}]}')
        assert notes == []

    def test_confidence_defaults_to_one_when_absent(self):
        notes = cultural._parse_cultural_response('{"notes": [{"note": "x"}]}')
        assert notes[0]["confidence"] == 1.0

    def test_confidence_clamped_to_valid_range(self):
        notes = cultural._parse_cultural_response(
            '{"notes": [{"note": "a", "confidence": 5.0}, {"note": "b", "confidence": -1.0}]}'
        )
        assert notes[0]["confidence"] == 1.0
        assert notes[1]["confidence"] == 0.0

    def test_non_numeric_confidence_defaults_to_one(self):
        notes = cultural._parse_cultural_response(
            '{"notes": [{"note": "x", "confidence": "not-a-number"}]}'
        )
        assert notes[0]["confidence"] == 1.0


class TestSelectConfidentNotes:
    def test_filters_below_threshold(self):
        from src.evaluation.policies import ABSTAIN_THRESHOLD

        notes = [
            {"note": "a", "confidence": ABSTAIN_THRESHOLD + 0.1},
            {"note": "b", "confidence": ABSTAIN_THRESHOLD - 0.1},
        ]
        kept = cultural._select_confident_notes(notes)
        assert [n["note"] for n in kept] == ["a"]

    def test_empty_input_yields_empty_output(self):
        assert cultural._select_confident_notes([]) == []
