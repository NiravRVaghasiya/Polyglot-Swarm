"""Phase 21 tests: user data export and deletion (src.memory.privacy)."""

from __future__ import annotations

from src.api import auth
from src.memory import (
    analytics,
    collocations,
    experiments,
    privacy,
    schema,
    session_history,
    skill_state,
    user_profile,
    vocabulary_db,
)
from src.memory.db import get_connection


def _seed_user(user_id: str) -> None:
    user_profile.create_profile(user_id, target_languages=["Spanish"])
    vocabulary_db.upsert_word(user_id, "Spanish", "mesa", translation="table")
    schema.init_all()
    with get_connection() as conn:  # rows no current code path writes
        conn.execute(
            "INSERT INTO collocations (user_id, language, phrase, created_at, updated_at) "
            "VALUES (?, 'Spanish', 'tomar una decisión', '', '')",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO skill_states (user_id, language, skill, mastery, uncertainty, "
            "sample_size, updated_at) VALUES (?, 'Spanish', 'grammar', 0.5, 0.5, 0, '')",
            (user_id,),
        )
    session_history.record_turn("s1", user_id, "Spanish", role="user", content="Hola")
    analytics.record_error(user_id, "Spanish", "ser_vs_estar")
    analytics.log_session(user_id, "Spanish")


class TestExportUserData:
    def test_exports_every_seeded_store(self, temp_storage):
        _seed_user("u1")
        data = privacy.export_user_data("u1")
        assert data["user_id"] == "u1"
        assert len(data["vocabulary"]) == 1
        assert len(data["collocations"]) == 1
        assert len(data["conversation_turns"]) == 1
        assert len(data["error_patterns"]) == 1
        assert len(data["learning_sessions"]) == 1
        assert len(data["skill_states"]) == 1
        assert data["profile"]["user_id"] == "u1"

    def test_export_scoped_to_the_requested_user(self, temp_storage):
        _seed_user("u1")
        vocabulary_db.upsert_word("u2", "Spanish", "silla", translation="chair")
        data = privacy.export_user_data("u1")
        assert all(v["word"] != "silla" for v in data["vocabulary"])
        assert len(data["vocabulary"]) == 1

    def test_export_for_unknown_user_does_not_raise(self, temp_storage):
        data = privacy.export_user_data("ghost")
        assert data["user_id"] == "ghost"
        assert data["vocabulary"] == []
        assert data["account"] is None
        assert data["profile"] is None

    def test_export_includes_experiment_participation(self, temp_storage):
        experiments.create_experiment("exp", ["a", "b"])
        experiments.assign("exp", "u1")
        experiments.record_outcome("exp", "u1", "pre_test", "metric", 1.0)
        data = privacy.export_user_data("u1")
        assert len(data["experiment_assignments"]) == 1
        assert len(data["outcomes"]) == 1

    def test_export_includes_account_row(self, temp_storage):
        user_id = auth.register("exportuser", "pw-secret-1")
        data = privacy.export_user_data(user_id)
        assert data["account"]["username"] == "exportuser"


class TestDeleteUserData:
    def test_removes_data_from_every_store(self, temp_storage):
        _seed_user("u1")
        result = privacy.delete_user_data("u1")

        assert vocabulary_db.get_all_for_user("u1") == []
        assert collocations.get_all_for_user("u1") == []
        assert session_history.get_recent_turns_for_user("u1") == []
        assert analytics.get_error_patterns("u1") == []
        assert analytics.get_sessions("u1") == []
        assert skill_state.get_all_skills_for_user("u1") == []
        assert user_profile.profile_exists("u1") is False

        assert result["vocabulary"] == 1
        assert result["collocations"] == 1
        assert result["conversation_turns"] == 1
        assert result["analytics"] == {"error_patterns": 1, "learning_sessions": 1}
        assert result["skill_states"] == 1
        assert result["profile"] is True

    def test_does_not_affect_other_users(self, temp_storage):
        _seed_user("u1")
        _seed_user("u2")
        privacy.delete_user_data("u1")
        assert vocabulary_db.get_all_for_user("u2") != []

    def test_deletes_account_and_invalidates_tokens(self, temp_storage):
        user_id = auth.register("deleteuser", "pw-secret-1")
        token = auth.login("deleteuser", "pw-secret-1")
        assert auth.resolve_token(token) == user_id

        result = privacy.delete_user_data(user_id)

        assert result["account"] is True
        assert result["auth_tokens"] == 1
        assert auth.resolve_token(token) is None

    def test_deletes_experiment_participation(self, temp_storage):
        experiments.create_experiment("exp", ["a", "b"])
        experiments.assign("exp", "u1")
        experiments.record_outcome("exp", "u1", "pre_test", "metric", 1.0)

        result = privacy.delete_user_data("u1")

        assert result["experiments"] == {"experiment_assignments": 1, "outcomes": 1}
        assert experiments.get_assignment("exp", "u1") is None
        assert experiments.get_outcomes("exp", user_id="u1") == []

    def test_anonymizes_rather_than_deletes_audit_log(self, temp_storage):
        from src.security.audit import log_event, recent_events

        log_event("login", user_id="u1", detail={"username": "u1name"})
        result = privacy.delete_user_data("u1")

        assert result["audit_log_anonymized"] == 1
        events = recent_events(event_type="login")
        assert events[0]["user_id"] is None
        assert events[0]["detail"] == {"username": "u1name"}  # event itself kept

    def test_delete_for_unknown_user_does_not_raise(self, temp_storage):
        result = privacy.delete_user_data("ghost")
        assert result["vocabulary"] == 0
        assert result["account"] is False

    def test_export_after_delete_is_empty(self, temp_storage):
        _seed_user("u1")
        privacy.delete_user_data("u1")
        data = privacy.export_user_data("u1")
        assert data["vocabulary"] == []
        assert data["profile"] is None
