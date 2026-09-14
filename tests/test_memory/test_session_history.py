"""Tests for the conversation session history store."""

from __future__ import annotations

from src.memory import session_history as sh


class TestRecordTurn:
    def test_auto_increments_turn_index(self, temp_storage):
        sh.record_turn("s1", "u1", "Spanish", role="user", content="Hola")
        sh.record_turn("s1", "u1", "Spanish", role="assistant", content="¡Buenas!")
        turns = sh.get_turns("s1")
        assert [t["turn_index"] for t in turns] == [0, 1]
        assert [t["role"] for t in turns] == ["user", "assistant"]

    def test_turns_isolated_per_session(self, temp_storage):
        sh.record_turn("s1", "u1", "Spanish", role="user", content="a")
        sh.record_turn("s2", "u1", "Spanish", role="user", content="b")
        assert len(sh.get_turns("s1")) == 1
        assert len(sh.get_turns("s2")) == 1

    def test_returns_row_id(self, temp_storage):
        rid = sh.record_turn("s1", "u1", "Spanish", role="user", content="hi")
        assert isinstance(rid, int) and rid > 0


class TestRecordTurns:
    def test_batch_records_in_order(self, temp_storage):
        added = sh.record_turns(
            "s1", "u1", "Spanish",
            [
                {"role": "user", "content": "Hola"},
                {"role": "assistant", "content": "¿Qué tal?"},
            ],
        )
        assert added == 2
        assert [t["content"] for t in sh.get_turns("s1")] == ["Hola", "¿Qué tal?"]

    def test_skips_incomplete_messages(self, temp_storage):
        added = sh.record_turns(
            "s1", "u1", "Spanish",
            [
                {"role": "user", "content": "ok"},
                {"role": "user"},          # missing content
                {"content": "no role"},    # missing role
            ],
        )
        assert added == 1


class TestRecentTurns:
    def test_newest_first(self, temp_storage):
        sh.record_turn("s1", "u1", "Spanish", role="user", content="first")
        sh.record_turn("s1", "u1", "Spanish", role="user", content="second")
        recent = sh.get_recent_turns_for_user("u1")
        assert recent[0]["content"] == "second"

    def test_filter_by_language(self, temp_storage):
        sh.record_turn("s1", "u1", "Spanish", role="user", content="es")
        sh.record_turn("s2", "u1", "Italian", role="user", content="it")
        recent = sh.get_recent_turns_for_user("u1", "Italian")
        assert [r["content"] for r in recent] == ["it"]
