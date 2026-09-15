"""End-to-end: memory persists across sessions via the lifecycle helpers."""

from __future__ import annotations

import pytest

from src.config import settings
from src.memory import analytics, session_history, user_profile, vocabulary_db
from src.orchestrator.lifecycle import build_initial_state, persist_session


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


class TestBuildInitialState:
    def test_seeds_from_profile(self, temp_storage):
        user_profile.create_profile(
            "u1",
            target_languages=["Italian"],
            cefr_by_language={"Italian": "B1"},
            interests=["cooking"],
        )
        state = build_initial_state("u1")
        assert state["user_id"] == "u1"
        assert state["language"] == "Italian"
        assert state["cefr_level"] == "B1"
        assert state["user_interests"] == ["cooking"]

    def test_language_override(self, temp_storage):
        user_profile.create_profile("u1", cefr_by_language={"Spanish": "A2"})
        state = build_initial_state("u1", "Spanish")
        assert state["language"] == "Spanish"

    def test_seeds_weaknesses(self, temp_storage):
        for _ in range(3):
            analytics.record_error("u1", "Spanish", "ser_vs_estar")
        state = build_initial_state("u1", "Spanish")
        assert "ser_vs_estar" in state["grammar_weaknesses"]

    def test_loads_due_reviews(self, temp_storage):
        vocabulary_db.upsert_word(
            "u1",
            "Spanish",
            "mesa",
            next_review="2020-01-01T00:00:00+00:00",  # long overdue
        )
        state = build_initial_state("u1", "Spanish")
        assert any(r["word"] == "mesa" for r in state["pending_reviews"])


class TestPersistSession:
    def _session_state(self, user_id="u1", language="Spanish"):
        state = build_initial_state(user_id, language)
        state["messages"] = [
            {"role": "user", "content": "Hola, una mesa para dos"},
            {"role": "assistant", "content": "¡Claro! Síganme."},
        ]
        state["new_vocabulary"] = [
            {
                "word": "mesa",
                "translation": "table",
                "pos": "noun",
                "context_sentence": "una mesa para dos",
            },
            {"word": "cuenta", "translation": "bill", "pos": "noun"},
        ]
        state["grammar_errors"] = [
            {
                "original": "yo soy hambre",
                "correction": "yo tengo hambre",
                "rule": "ser_vs_tener",
                "explanation": "",
                "severity": "moderate",
            },
        ]
        return state

    def test_persists_counts(self, temp_storage):
        counts = persist_session(self._session_state())
        # Belief-layer counts unchanged; Phase 3 adds an evidence-event count.
        assert counts["vocabulary"] == 2
        assert counts["grammar_errors"] == 1
        assert counts["turns"] == 2
        # 1 user turn + 1 grammar error + 2 vocab = 4 evidence events.
        assert counts["events"] == 4

    def test_vocab_written_to_db(self, temp_storage):
        persist_session(self._session_state())
        words = {w["word"] for w in vocabulary_db.get_all_for_user("u1", "Spanish")}
        assert words == {"mesa", "cuenta"}

    def test_errors_written_to_db(self, temp_storage):
        persist_session(self._session_state())
        patterns = analytics.get_error_patterns("u1", "Spanish")
        assert any(p["error_type"] == "ser_vs_tener" for p in patterns)

    def test_turns_written(self, temp_storage):
        state = self._session_state()
        persist_session(state)
        assert len(session_history.get_turns(state["session_id"])) == 2

    def test_session_logged(self, temp_storage):
        persist_session(self._session_state())
        sessions = analytics.get_sessions("u1", "Spanish")
        assert len(sessions) == 1
        assert sessions[0]["new_words_learned"] == 2


class TestAnalyticsFailureIsolation:
    """Phase 23: an analytics-store failure must not block session finalization.

    Before this, an exception from analytics.record_error/log_session would
    propagate out of persist_session and prevent sessions.end_session (and the
    knowledge-model update after it) from ever running for that call.
    """

    def _session_state(self, user_id="u1", language="Spanish"):
        state = build_initial_state(user_id, language)
        state["messages"] = [{"role": "user", "content": "hola"}]
        state["grammar_errors"] = [
            {
                "original": "yo soy hambre",
                "correction": "yo tengo hambre",
                "rule": "ser_vs_tener",
                "explanation": "",
                "severity": "moderate",
            },
        ]
        return state

    def test_record_error_failure_does_not_raise(self, temp_storage, monkeypatch):
        monkeypatch.setattr(
            analytics,
            "record_error",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )

        counts = persist_session(self._session_state())  # must not raise
        assert counts["grammar_errors"] == 0  # failed write, not counted

    def test_log_session_failure_does_not_raise(self, temp_storage, monkeypatch):
        monkeypatch.setattr(
            analytics,
            "log_session",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )

        persist_session(self._session_state())  # must not raise

    def test_session_still_marked_completed_when_analytics_fails(self, temp_storage, monkeypatch):
        from src.memory import sessions

        monkeypatch.setattr(
            analytics,
            "log_session",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        monkeypatch.setattr(
            analytics,
            "record_error",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )

        state = self._session_state()
        persist_session(state)

        record = sessions.get_session(state["session_id"])
        assert record is not None
        assert record["status"] == "completed"

    def test_vocabulary_still_persisted_when_analytics_fails(self, temp_storage, monkeypatch):
        monkeypatch.setattr(
            analytics,
            "log_session",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )

        state = self._session_state()
        state["new_vocabulary"] = [{"word": "mesa", "translation": "table", "pos": "noun"}]
        persist_session(state)

        words = {w["word"] for w in vocabulary_db.get_all_for_user("u1", "Spanish")}
        assert words == {"mesa"}


class TestCrossSessionMemory:
    def test_learned_words_due_next_session(self, temp_storage):
        # Session 1: learn a word.
        s1 = build_initial_state("learner", "Spanish")
        s1["new_vocabulary"] = [{"word": "propina", "translation": "tip"}]
        persist_session(s1)

        # The word was scheduled a day out; simulate time passing by asking the
        # store for items due well into the future.
        due = vocabulary_db.get_due("learner", "Spanish", now="2099-01-01T00:00:00+00:00")
        assert any(d["word"] == "propina" for d in due)

    def test_weakness_carries_into_new_state(self, temp_storage):
        s1 = build_initial_state("learner", "Spanish")
        s1["grammar_errors"] = [
            {
                "rule": "subjunctive",
                "original": "",
                "correction": "",
                "explanation": "",
                "severity": "moderate",
            },
        ]
        persist_session(s1)

        s2 = build_initial_state("learner", "Spanish")
        assert "subjunctive" in s2["grammar_weaknesses"]
