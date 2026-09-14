"""Tests for the SQLite vocabulary store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.memory import vocabulary_db as vdb


def _iso(dt):
    return dt.isoformat()


class TestUpsert:
    def test_insert_new_word(self, temp_storage):
        row = vdb.upsert_word(
            "u1", "Spanish", "mesa",
            translation="table", pos="noun", cefr_level="A1",
            context="Una mesa para dos",
        )
        assert row["word"] == "mesa"
        assert row["translation"] == "table"
        assert row["times_seen"] == 1
        assert row["contexts"] == ["Una mesa para dos"]

    def test_upsert_accumulates_and_appends_context(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "mesa", context="Una mesa para dos")
        row = vdb.upsert_word("u1", "Spanish", "mesa", context="La mesa está sucia")

        assert row["times_seen"] == 2
        assert row["contexts"] == ["Una mesa para dos", "La mesa está sucia"]

    def test_upsert_dedups_context(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "mesa", context="repeat")
        row = vdb.upsert_word("u1", "Spanish", "mesa", context="repeat")
        assert row["contexts"] == ["repeat"]

    def test_upsert_fills_empty_metadata_only(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "mesa", translation="table")
        # Empty translation must not wipe the existing value.
        row = vdb.upsert_word("u1", "Spanish", "mesa", translation="")
        assert row["translation"] == "table"

    def test_scoped_by_user_and_language(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "mesa")
        vdb.upsert_word("u2", "Spanish", "mesa")
        vdb.upsert_word("u1", "Italian", "mesa")

        assert vdb.count_for_user("u1") == 2
        assert vdb.count_for_user("u1", "Spanish") == 1
        assert vdb.count_for_user("u2") == 1


class TestReviewOutcome:
    def test_records_correct(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "mesa")
        vdb.record_review_outcome("u1", "Spanish", "mesa", correct=True)
        row = vdb.get_all_for_user("u1")[0]
        assert row["times_correct"] == 1
        assert row["times_incorrect"] == 0

    def test_records_incorrect(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "mesa")
        vdb.record_review_outcome("u1", "Spanish", "mesa", correct=False)
        row = vdb.get_all_for_user("u1")[0]
        assert row["times_incorrect"] == 1


class TestGetDue:
    def test_returns_only_due(self, temp_storage):
        now = datetime.now(timezone.utc)
        past = _iso(now - timedelta(hours=1))
        future = _iso(now + timedelta(days=2))

        vdb.upsert_word("u1", "Spanish", "due_word", next_review=past)
        vdb.upsert_word("u1", "Spanish", "future_word", next_review=future)

        due = vdb.get_due("u1")
        assert [d["word"] for d in due] == ["due_word"]

    def test_orders_most_overdue_first(self, temp_storage):
        now = datetime.now(timezone.utc)
        vdb.upsert_word("u1", "Spanish", "recent", next_review=_iso(now - timedelta(minutes=5)))
        vdb.upsert_word("u1", "Spanish", "old", next_review=_iso(now - timedelta(days=3)))

        due = vdb.get_due("u1")
        assert [d["word"] for d in due] == ["old", "recent"]

    def test_respects_limit(self, temp_storage):
        now = datetime.now(timezone.utc)
        past = _iso(now - timedelta(hours=1))
        for i in range(10):
            vdb.upsert_word("u1", "Spanish", f"w{i}", next_review=past)
        assert len(vdb.get_due("u1", limit=3)) == 3

    def test_filters_by_language(self, temp_storage):
        now = datetime.now(timezone.utc)
        past = _iso(now - timedelta(hours=1))
        vdb.upsert_word("u1", "Spanish", "es_word", next_review=past)
        vdb.upsert_word("u1", "Italian", "it_word", next_review=past)

        due = vdb.get_due("u1", language="Italian")
        assert [d["word"] for d in due] == ["it_word"]

    def test_words_without_review_not_due(self, temp_storage):
        vdb.upsert_word("u1", "Spanish", "no_schedule")
        assert vdb.get_due("u1") == []


class TestCardState:
    def test_card_state_round_trips_as_dict(self, temp_storage):
        card = {"stability": 1.2, "difficulty": 5.0, "reps": 1}
        vdb.upsert_word("u1", "Spanish", "mesa", card_state=card, next_review="2026-01-01T00:00:00+00:00")
        row = vdb.get_all_for_user("u1")[0]
        assert row["card_state"] == card
