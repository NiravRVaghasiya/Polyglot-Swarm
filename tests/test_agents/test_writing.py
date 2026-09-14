"""Tests for writing exercises with detailed feedback."""

from __future__ import annotations

import pytest

from src.agents import writing
from src.config import settings
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    return data_dir


_FEEDBACK = (
    '{"corrections": ['
    '{"original": "yo soy hambre", "correction": "yo tengo hambre", '
    '"rule": "ser_vs_tener", "explanation": "Use tener for physical states."}'
    '], "style_notes": ["Vary your sentence openings."], '
    '"overall": "Good effort! Watch ser vs tener.", '
    '"corrected_text": "Yo tengo hambre."}'
)


class TestAssessWriting:
    async def test_structured_feedback_with_rule(self, temp_storage, monkeypatch):
        monkeypatch.setattr(writing, "get_provider", lambda tier: FakeProvider(_FEEDBACK))
        result = await writing.assess_writing("Spanish", "yo soy hambre")

        assert result["corrections"][0]["rule"] == "ser_vs_tener"
        assert result["corrections"][0]["correction"] == "yo tengo hambre"
        assert result["style_notes"] == ["Vary your sentence openings."]
        assert result["corrected_text"] == "Yo tengo hambre."

    async def test_empty_text_no_call(self, temp_storage, monkeypatch):
        def boom(tier):
            raise AssertionError("should not call LLM for empty text")

        monkeypatch.setattr(writing, "get_provider", boom)
        result = await writing.assess_writing("Spanish", "   ")
        assert result["corrections"] == []

    async def test_records_errors_to_taxonomy(self, temp_storage, monkeypatch):
        monkeypatch.setattr(writing, "get_provider", lambda tier: FakeProvider(_FEEDBACK))
        await writing.assess_writing("Spanish", "yo soy hambre", user_id="u1")

        from src.memory import analytics

        patterns = analytics.get_error_patterns("u1", "Spanish")
        assert any(p["error_type"] == "ser_vs_tener" for p in patterns)

    async def test_no_user_id_skips_persistence(self, temp_storage, monkeypatch):
        monkeypatch.setattr(writing, "get_provider", lambda tier: FakeProvider(_FEEDBACK))
        await writing.assess_writing("Spanish", "yo soy hambre")  # no user_id

        from src.memory import analytics

        assert analytics.get_error_patterns("u1", "Spanish") == []

    async def test_llm_failure_returns_empty(self, temp_storage, monkeypatch):
        class Boom(LLMProvider):
            name = "boom"

            def is_available(self):
                return True

            async def generate(self, *a, **k):
                raise RuntimeError("down")

        monkeypatch.setattr(writing, "get_provider", lambda tier: Boom())
        result = await writing.assess_writing("Spanish", "hola", user_id="u1")
        assert result["corrections"] == []

    async def test_skips_corrections_without_original(self, temp_storage, monkeypatch):
        payload = '{"corrections": [{"correction": "x", "rule": "y"}], "overall": "ok"}'
        monkeypatch.setattr(writing, "get_provider", lambda tier: FakeProvider(payload))
        result = await writing.assess_writing("Spanish", "hola")
        assert result["corrections"] == []


class TestFormat:
    def test_renders_corrections(self):
        result = {
            "corrections": [
                {"original": "a", "correction": "b", "rule": "r", "explanation": "why"}
            ],
            "style_notes": ["note"],
            "overall": "Great job",
            "corrected_text": "b",
        }
        text = writing.format_writing_feedback(result)
        assert "a → b" in text
        assert "[r]" in text
        assert "Great job" in text

    def test_no_corrections_message(self):
        text = writing.format_writing_feedback(
            {"corrections": [], "style_notes": [], "overall": ""}
        )
        assert "nicely done" in text.lower()
