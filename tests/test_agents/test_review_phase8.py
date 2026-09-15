"""Phase 8 tests: contextual review generation and recall-measuring grading
(FSRS + evidence + dimension + mastery)."""

from __future__ import annotations

import pytest

from src.agents import review
from src.agents.review import generate_contextual_review, grade_review
from src.evidence import store
from src.llm.provider import LLMProvider
from src.memory import skill_state, vocabulary_db


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    from src.config import settings

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


class _FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


class TestContextualReview:
    async def test_generates_contextual_cue(self, monkeypatch):
        payload = '{"cue": "En el restaurante pides una ___ para dos.", "expected": "mesa"}'
        monkeypatch.setattr(review, "get_provider", lambda tier: _FakeProvider(payload))
        result = await generate_contextual_review(
            {"word": "mesa", "translation": "table"}, "Spanish"
        )
        assert "mesa" not in result["cue"]  # word not given away
        assert result["expected"] == "mesa"
        assert result["word"] == "mesa"

    async def test_falls_back_on_bad_output(self, monkeypatch):
        monkeypatch.setattr(review, "get_provider", lambda tier: _FakeProvider("not json"))
        result = await generate_contextual_review(
            {"word": "mesa", "contexts": ["una mesa"]}, "Spanish"
        )
        # Fallback cue still references the word so review works offline.
        assert "mesa" in result["cue"]
        assert result["expected"] == "mesa"

    async def test_scenario_hint_included(self, monkeypatch):
        captured = {}

        class Cap(_FakeProvider):
            async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
                captured["prompt"] = messages[-1].content
                return '{"cue": "cue", "expected": "mesa"}'

        monkeypatch.setattr(review, "get_provider", lambda tier: Cap(""))
        await generate_contextual_review(
            {"word": "mesa"}, "Spanish", scenario={"title": "Restaurant", "location": "Madrid"}
        )
        assert "Restaurant" in captured["prompt"]


class TestGradeReview:
    def _seed(self):
        vocabulary_db.upsert_word(
            "u1",
            "Spanish",
            "mesa",
            translation="table",
            next_review="2020-01-01T00:00:00+00:00",
        )

    def test_successful_recall_updates_everything(self, temp_storage):
        self._seed()
        result = grade_review("u1", "Spanish", "mesa", rating=3, session_id="s1")

        assert result["correct"] is True
        assert result["next_review"]
        # Counter, dimension, evidence, and skill belief all updated.
        row = vocabulary_db.get_all_for_user("u1", "Spanish")[0]
        assert row["times_correct"] == 1
        assert row["recognition"] > 0.0
        events = store.get_events("u1", "Spanish", event_type="REVIEW_RESULT")
        assert len(events) == 1
        assert events[0]["assessment"] == "correct"
        assert events[0]["confidence"] == 0.95
        skills = skill_state.get_skills("u1", "Spanish")
        assert skills["vocabulary"]["mastery"] > 0.0

    def test_failed_recall_records_incorrect(self, temp_storage):
        self._seed()
        result = grade_review("u1", "Spanish", "mesa", rating=1, session_id="s1")
        assert result["correct"] is False
        row = vocabulary_db.get_all_for_user("u1", "Spanish")[0]
        assert row["times_incorrect"] == 1
        events = store.get_events("u1", "Spanish", event_type="REVIEW_RESULT")
        assert events[0]["assessment"] == "incorrect"

    def test_grade_without_prior_card_still_works(self, temp_storage):
        # Word exists but no card_state -> grading schedules a fresh card.
        vocabulary_db.upsert_word("u1", "Spanish", "silla")
        result = grade_review("u1", "Spanish", "silla", rating=4)
        assert result["next_review"]
        assert result["correct"] is True

    def test_next_review_advances_on_good(self, temp_storage):
        self._seed()
        before = vocabulary_db.get_all_for_user("u1", "Spanish")[0]["next_review"]
        result = grade_review("u1", "Spanish", "mesa", rating=4)  # Easy -> long interval
        assert result["next_review"] > before
