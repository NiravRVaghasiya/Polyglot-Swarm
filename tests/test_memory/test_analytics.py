"""Tests for grammar error patterns and session/analytics logging."""

from __future__ import annotations

from src.memory import analytics


class TestErrorPatterns:
    def test_record_creates_pattern(self, temp_storage):
        row = analytics.record_error("u1", "Spanish", "ser_vs_estar")
        assert row["occurrences"] == 1
        assert row["mastered"] == 0

    def test_frequency_increments(self, temp_storage):
        analytics.record_error("u1", "Spanish", "ser_vs_estar")
        row = analytics.record_error("u1", "Spanish", "ser_vs_estar")
        assert row["occurrences"] == 2

    def test_scoped_by_user_language_and_type(self, temp_storage):
        analytics.record_error("u1", "Spanish", "ser_vs_estar")
        analytics.record_error("u1", "Spanish", "gender_agreement")
        analytics.record_error("u2", "Spanish", "ser_vs_estar")
        analytics.record_error("u1", "Italian", "ser_vs_estar")

        u1_es = analytics.get_error_patterns("u1", "Spanish")
        assert {p["error_type"] for p in u1_es} == {"ser_vs_estar", "gender_agreement"}

    def test_mark_mastered(self, temp_storage):
        analytics.record_error("u1", "Spanish", "ser_vs_estar")
        analytics.mark_mastered("u1", "Spanish", "ser_vs_estar")

        patterns = analytics.get_error_patterns("u1", "Spanish")
        assert patterns[0]["mastered"] == 1
        assert patterns[0]["mastered_date"] is not None

    def test_reoccurrence_resets_mastery(self, temp_storage):
        analytics.record_error("u1", "Spanish", "ser_vs_estar")
        analytics.mark_mastered("u1", "Spanish", "ser_vs_estar")
        # Learner makes the mistake again -> no longer mastered.
        row = analytics.record_error("u1", "Spanish", "ser_vs_estar")
        assert row["mastered"] == 0
        assert row["mastered_date"] is None

    def test_include_mastered_filter(self, temp_storage):
        analytics.record_error("u1", "Spanish", "mastered_one")
        analytics.record_error("u1", "Spanish", "active_one")
        analytics.mark_mastered("u1", "Spanish", "mastered_one")

        active = analytics.get_error_patterns("u1", "Spanish", include_mastered=False)
        assert {p["error_type"] for p in active} == {"active_one"}

    def test_ordered_by_frequency(self, temp_storage):
        for _ in range(3):
            analytics.record_error("u1", "Spanish", "frequent")
        analytics.record_error("u1", "Spanish", "rare")

        patterns = analytics.get_error_patterns("u1", "Spanish")
        assert patterns[0]["error_type"] == "frequent"

    def test_top_weaknesses_excludes_mastered(self, temp_storage):
        for _ in range(5):
            analytics.record_error("u1", "Spanish", "big_problem")
        analytics.record_error("u1", "Spanish", "small_problem")
        analytics.record_error("u1", "Spanish", "solved")
        analytics.mark_mastered("u1", "Spanish", "solved")

        top = analytics.top_weaknesses("u1", "Spanish", limit=2)
        assert top == ["big_problem", "small_problem"]


class TestSessions:
    def test_log_and_read_back(self, temp_storage):
        analytics.log_session(
            "u1", "Spanish",
            session_type="conversation",
            duration_minutes=12.5,
            words_practiced=8,
            new_words_learned=3,
            grammar_errors=2,
            grammar_errors_corrected=1,
            cefr_estimate="A2",
        )
        sessions = analytics.get_sessions("u1", "Spanish")
        assert len(sessions) == 1
        s = sessions[0]
        assert s["duration_minutes"] == 12.5
        assert s["new_words_learned"] == 3
        assert s["cefr_estimate"] == "A2"

    def test_returns_row_id(self, temp_storage):
        rid = analytics.log_session("u1", "Spanish")
        assert isinstance(rid, int) and rid > 0

    def test_most_recent_first(self, temp_storage):
        analytics.log_session("u1", "Spanish", timestamp="2026-01-01T00:00:00+00:00")
        analytics.log_session("u1", "Spanish", timestamp="2026-02-01T00:00:00+00:00")
        sessions = analytics.get_sessions("u1", "Spanish")
        assert sessions[0]["timestamp"] == "2026-02-01T00:00:00+00:00"

    def test_scoped_by_user(self, temp_storage):
        analytics.log_session("u1", "Spanish")
        analytics.log_session("u2", "Spanish")
        assert len(analytics.get_sessions("u1")) == 1

    def test_filter_by_language(self, temp_storage):
        analytics.log_session("u1", "Spanish")
        analytics.log_session("u1", "Italian")
        assert len(analytics.get_sessions("u1", "Italian")) == 1
