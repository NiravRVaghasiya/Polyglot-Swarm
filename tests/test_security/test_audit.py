"""Phase 21 tests: the append-only security audit log."""

from __future__ import annotations

from src.security.audit import anonymize_for_user, log_event, recent_events


class TestLogEvent:
    def test_returns_a_row_id(self, temp_storage):
        row_id = log_event("login", user_id="u1")
        assert isinstance(row_id, int) and row_id > 0

    def test_persists_detail(self, temp_storage):
        log_event("login", user_id="u1", detail={"username": "alice"})
        events = recent_events(user_id="u1")
        assert events[0]["detail"] == {"username": "alice"}

    def test_user_id_optional(self, temp_storage):
        row_id = log_event("system_startup")
        assert row_id > 0
        events = recent_events(event_type="system_startup")
        assert events[0]["user_id"] is None

    def test_unserializable_detail_falls_back_to_empty_dict(self, temp_storage):
        class Unserializable:
            pass

        log_event("weird_event", detail={"obj": Unserializable()})
        events = recent_events(event_type="weird_event")
        assert events[0]["detail"] == {}


class TestRecentEvents:
    def test_most_recent_first(self, temp_storage):
        log_event("login", user_id="u1", detail={"n": 1})
        log_event("login", user_id="u1", detail={"n": 2})
        events = recent_events(user_id="u1")
        assert events[0]["detail"]["n"] == 2
        assert events[1]["detail"]["n"] == 1

    def test_filters_by_user_id(self, temp_storage):
        log_event("login", user_id="u1")
        log_event("login", user_id="u2")
        assert len(recent_events(user_id="u1")) == 1

    def test_filters_by_event_type(self, temp_storage):
        log_event("login", user_id="u1")
        log_event("logout", user_id="u1")
        assert len(recent_events(user_id="u1", event_type="login")) == 1

    def test_respects_limit(self, temp_storage):
        for _ in range(5):
            log_event("login", user_id="u1")
        assert len(recent_events(user_id="u1", limit=2)) == 2

    def test_no_filters_returns_everything(self, temp_storage):
        log_event("login", user_id="u1")
        log_event("register", user_id="u2")
        assert len(recent_events()) == 2


class TestAnonymizeForUser:
    def test_nulls_user_id_but_keeps_the_event(self, temp_storage):
        log_event("login", user_id="u1", detail={"username": "alice"})
        updated = anonymize_for_user("u1")
        assert updated == 1
        events = recent_events(event_type="login")
        assert events[0]["user_id"] is None
        assert events[0]["detail"] == {"username": "alice"}

    def test_does_not_affect_other_users(self, temp_storage):
        log_event("login", user_id="u1")
        log_event("login", user_id="u2")
        anonymize_for_user("u1")
        events = recent_events(event_type="login")
        user_ids = {e["user_id"] for e in events}
        assert user_ids == {None, "u2"}

    def test_no_matching_rows_returns_zero(self, temp_storage):
        assert anonymize_for_user("nobody") == 0
