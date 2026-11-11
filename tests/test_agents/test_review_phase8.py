"""Phase 8 tests: recall-measuring review grading (FSRS + evidence + dimension +
mastery)."""

from __future__ import annotations

import pytest

from src.agents.review import grade_review
from src.evidence import store
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
