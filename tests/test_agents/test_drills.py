"""Tests for targeted drill generation."""

from __future__ import annotations

import pytest

from src.agents import drills
from src.config import settings
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.last_prompt = ""

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.last_prompt = messages[-1].content
        return self.reply


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    return data_dir


_DRILL_PAYLOAD = (
    '{"drills": [{"type": "grammar", "target": "ser_vs_estar", '
    '"prompt": "Ella ___ cansada hoy.", "answer": "está", "confusable": "es"}]}'
)


class TestGenerateDrills:
    async def test_targets_weakness(self, temp_storage, monkeypatch):
        from src.memory import analytics

        for _ in range(3):
            analytics.record_error("u1", "Spanish", "ser_vs_estar")

        fake = FakeProvider(_DRILL_PAYLOAD)
        monkeypatch.setattr(drills, "get_provider", lambda tier: fake)

        result = await drills.generate_drills("u1", "Spanish")
        assert result[0]["target"] == "ser_vs_estar"
        assert result[0]["confusable"] == "es"
        # The weakness was passed into the prompt.
        assert "ser_vs_estar" in fake.last_prompt

    async def test_targets_due_vocab(self, temp_storage, monkeypatch):
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word(
            "u1", "Spanish", "propina", next_review="2020-01-01T00:00:00+00:00"
        )
        fake = FakeProvider(
            '{"drills": [{"type": "vocab", "target": "propina", '
            '"prompt": "Dejé una ___ al camarero.", "answer": "propina"}]}'
        )
        monkeypatch.setattr(drills, "get_provider", lambda tier: fake)

        result = await drills.generate_drills("u1", "Spanish")
        assert result[0]["type"] == "vocab"
        assert "propina" in fake.last_prompt

    async def test_no_weaknesses_or_due_returns_empty(self, temp_storage, monkeypatch):
        def boom(tier):
            raise AssertionError("should not call the LLM with nothing to drill")

        monkeypatch.setattr(drills, "get_provider", boom)
        assert await drills.generate_drills("fresh_user", "Spanish") == []

    async def test_llm_failure_returns_empty(self, temp_storage, monkeypatch):
        from src.memory import analytics

        analytics.record_error("u1", "Spanish", "gender")

        class Boom(LLMProvider):
            name = "boom"

            def is_available(self):
                return True

            async def generate(self, *a, **k):
                raise RuntimeError("down")

        monkeypatch.setattr(drills, "get_provider", lambda tier: Boom())
        assert await drills.generate_drills("u1", "Spanish") == []

    async def test_skips_drills_without_prompt(self, temp_storage, monkeypatch):
        from src.memory import analytics

        analytics.record_error("u1", "Spanish", "gender")
        fake = FakeProvider('{"drills": [{"type": "grammar", "target": "x"}]}')
        monkeypatch.setattr(drills, "get_provider", lambda tier: fake)
        assert await drills.generate_drills("u1", "Spanish") == []


class TestDrillsNode:
    async def test_populates_pending_reviews(self, temp_storage, monkeypatch):
        from src.memory import analytics

        analytics.record_error("u1", "Spanish", "ser_vs_estar")
        monkeypatch.setattr(drills, "get_provider", lambda tier: FakeProvider(_DRILL_PAYLOAD))

        state = {"user_id": "u1", "language": "Spanish", "cefr_level": "A2"}
        result = await drills.drills_node(state)
        assert len(result["pending_reviews"]) == 1
        assert "drill" in result["agent_response"].lower()

    async def test_empty_when_nothing_to_drill(self, temp_storage, monkeypatch):
        monkeypatch.setattr(drills, "get_provider", lambda tier: FakeProvider('{"drills": []}'))
        state = {"user_id": "fresh", "language": "Spanish", "cefr_level": "A2"}
        result = await drills.drills_node(state)
        assert result["pending_reviews"] == []
        assert "No drills" in result["agent_response"]
