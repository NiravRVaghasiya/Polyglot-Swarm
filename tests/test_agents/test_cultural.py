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
            cultural, "get_provider",
            lambda tier: (captured.update(tier=tier) or fake),
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
