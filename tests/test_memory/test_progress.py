"""Tests for progress analytics aggregation queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.memory import analytics, progress


def _iso(d):
    return d.isoformat()


class TestVocabularyGrowth:
    def test_cumulative_series(self, temp_storage):
        analytics.log_session(
            "u1", "Spanish", new_words_learned=3, timestamp="2026-01-01T10:00:00+00:00"
        )
        analytics.log_session(
            "u1", "Spanish", new_words_learned=2, timestamp="2026-01-02T10:00:00+00:00"
        )
        # Two sessions same day accumulate.
        analytics.log_session(
            "u1", "Spanish", new_words_learned=1, timestamp="2026-01-02T18:00:00+00:00"
        )

        series = progress.vocabulary_growth("u1", "Spanish", days=100000)
        assert series[0] == {"date": "2026-01-01", "new_words": 3, "cumulative": 3}
        assert series[1] == {"date": "2026-01-02", "new_words": 3, "cumulative": 6}

    def test_respects_day_window(self, temp_storage):
        old = _iso(datetime.now(UTC) - timedelta(days=60))
        recent = _iso(datetime.now(UTC) - timedelta(days=1))
        analytics.log_session("u1", "Spanish", new_words_learned=5, timestamp=old)
        analytics.log_session("u1", "Spanish", new_words_learned=2, timestamp=recent)

        series = progress.vocabulary_growth("u1", "Spanish", days=30)
        total = series[-1]["cumulative"] if series else 0
        assert total == 2  # old session excluded

    def test_empty(self, temp_storage):
        assert progress.vocabulary_growth("nobody", "Spanish") == []


class TestTopWeaknesses:
    def test_ranked_and_excludes_mastered(self, temp_storage):
        for _ in range(4):
            analytics.record_error("u1", "Spanish", "ser_vs_estar")
        analytics.record_error("u1", "Spanish", "gender")
        analytics.record_error("u1", "Spanish", "solved")
        analytics.mark_mastered("u1", "Spanish", "solved")

        top = progress.top_weaknesses("u1", "Spanish")
        types = [w["error_type"] for w in top]
        assert types[0] == "ser_vs_estar"
        assert "solved" not in types

    def test_limit(self, temp_storage):
        for i in range(8):
            analytics.record_error("u1", "Spanish", f"e{i}")
        assert len(progress.top_weaknesses("u1", "Spanish", limit=3)) == 3


class TestCefrProgression:
    def test_series(self, temp_storage):
        analytics.log_session(
            "u1", "Spanish", cefr_estimate="A2", timestamp="2026-01-01T00:00:00+00:00"
        )
        analytics.log_session(
            "u1", "Spanish", cefr_estimate="B1", timestamp="2026-02-01T00:00:00+00:00"
        )
        prog = progress.cefr_progression("u1", "Spanish")
        assert [p["cefr"] for p in prog] == ["A2", "B1"]

    def test_ignores_null_estimates(self, temp_storage):
        analytics.log_session("u1", "Spanish", cefr_estimate=None)
        assert progress.cefr_progression("u1", "Spanish") == []


class TestStreak:
    def test_consecutive_days(self, temp_storage):
        base = datetime(2026, 3, 10, tzinfo=UTC).date()
        for offset in (0, 1, 2):
            day = base - timedelta(days=offset)
            analytics.log_session("u1", "Spanish", timestamp=f"{day.isoformat()}T12:00:00+00:00")
        assert progress.current_streak("u1", "Spanish", today="2026-03-10") == 3

    def test_broken_streak(self, temp_storage):
        analytics.log_session("u1", "Spanish", timestamp="2026-03-10T12:00:00+00:00")
        analytics.log_session("u1", "Spanish", timestamp="2026-03-07T12:00:00+00:00")
        assert progress.current_streak("u1", "Spanish", today="2026-03-10") == 1

    def test_counts_from_yesterday(self, temp_storage):
        # Studied yesterday but not today -> streak still counts.
        analytics.log_session("u1", "Spanish", timestamp="2026-03-09T12:00:00+00:00")
        assert progress.current_streak("u1", "Spanish", today="2026-03-10") == 1

    def test_no_sessions(self, temp_storage):
        assert progress.current_streak("nobody", "Spanish") == 0


class TestOverview:
    def test_combines_metrics(self, temp_storage):
        recent = _iso(datetime.now(UTC))
        analytics.log_session(
            "u1", "Spanish", new_words_learned=4, cefr_estimate="A2", timestamp=recent
        )
        for _ in range(2):
            analytics.record_error("u1", "Spanish", "ser_vs_estar")

        overview = progress.progress_overview("u1", "Spanish")
        assert overview["total_sessions"] == 1
        assert overview["words_learned_total"] == 4
        assert overview["current_cefr"] == "A2"
        assert overview["top_weaknesses"][0]["error_type"] == "ser_vs_estar"
