"""Phase 2 tests: schema migrations, canonical tables, SQLite-backed profiles,
session lifecycle, and the end-to-end resume flow."""

from __future__ import annotations

import pytest

from src.memory import (
    assessments,
    experiments,
    model_runs,
    profiles_db,
    schema,
    sessions,
    skill_state,
    user_profile,
)


class TestMigrations:
    def test_init_all_sets_version(self, temp_storage):
        schema.init_all()
        assert schema.current_version() == schema.SCHEMA_VERSION

    def test_migrations_are_idempotent(self, temp_storage):
        schema.init_all()
        v1 = schema.current_version()
        schema.init_all()
        assert schema.current_version() == v1

    def test_run_migrations_returns_target(self, temp_storage):
        assert schema.run_migrations() == schema.SCHEMA_VERSION

    def test_all_canonical_tables_exist(self, temp_storage):
        schema.init_all()
        from src.memory.db import get_connection

        with get_connection() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {r["name"] for r in rows}
        expected = {
            "profiles",
            "sessions",
            "skill_states",
            "learner_state_snapshots",
            "evidence",
            "assessments",
            "experiments",
            "experiment_assignments",
            "model_runs",
            "session_interactions",  # Phase 17 observability link table
            "outcomes",  # Phase 19 experiment outcomes
            # existing tables must also be provisioned by init_all
            "users",
            "vocabulary",
            "conversation_turns",
            "error_patterns",
            "learning_sessions",
        }
        assert expected <= tables


class TestProfilesDb:
    def test_save_and_get_round_trip(self, temp_storage):
        profiles_db.save(
            {
                "user_id": "u1",
                "native_language": "English",
                "target_languages": ["Spanish", "Polish"],
                "cefr_by_language": {"Spanish": "B1"},
                "goals": ["travel"],
                "interests": ["food"],
                "preferences": {"voice": True},
            }
        )
        got = profiles_db.get("u1")
        assert got is not None
        assert got["target_languages"] == ["Spanish", "Polish"]
        assert got["cefr_by_language"] == {"Spanish": "B1"}
        assert got["preferences"] == {"voice": True}

    def test_missing_profile_returns_none(self, temp_storage):
        assert profiles_db.get("nobody") is None


class TestProfileWriteThrough:
    def test_save_profile_writes_to_sqlite(self, temp_storage):
        p = user_profile.create_profile("u2", interests=["music"])
        # SQLite is now the source of truth.
        assert profiles_db.exists("u2")
        stored = profiles_db.get("u2")
        assert stored is not None
        assert stored["interests"] == ["music"]
        assert p.interests == ["music"]

    def test_load_prefers_sqlite(self, temp_storage):
        user_profile.create_profile("u3", cefr_by_language={"Spanish": "C1"})
        loaded = user_profile.load_profile("u3")
        assert loaded.cefr_for("Spanish") == "C1"

    def test_missing_profile_still_returns_default_without_writing(self, temp_storage):
        prof = user_profile.load_profile("ghost")
        assert prof.user_id == "ghost"
        assert not profiles_db.exists("ghost")


class TestSessions:
    def test_start_and_get(self, temp_storage):
        sessions.start_session("s1", "u1", "Spanish", scenario_id="es_restaurant_ordering")
        s = sessions.get_session("s1")
        assert s is not None
        assert s["status"] == "active"
        assert s["scenario_id"] == "es_restaurant_ordering"

    def test_start_is_idempotent(self, temp_storage):
        sessions.start_session("s1", "u1", "Spanish")
        sessions.start_session("s1", "u1", "Spanish", mode="review")
        assert sessions.get_session("s1")["mode"] == "review"

    def test_end_session(self, temp_storage):
        sessions.start_session("s1", "u1", "Spanish")
        sessions.end_session("s1")
        s = sessions.get_session("s1")
        assert s["status"] == "completed"
        assert s["ended_at"] is not None

    def test_latest_resumable(self, temp_storage):
        sessions.start_session("s1", "u1", "Spanish")
        sessions.start_session("s2", "u1", "Spanish")
        sessions.end_session("s1")
        resumable = sessions.latest_resumable("u1", "Spanish")
        assert resumable is not None
        assert resumable["session_id"] == "s2"


class TestSkillState:
    def test_upsert_and_get(self, temp_storage):
        skill_state.upsert_skill("u1", "Spanish", "grammar", mastery=0.52, uncertainty=0.1)
        skills = skill_state.get_skills("u1", "Spanish")
        assert skills["grammar"]["mastery"] == 0.52

    def test_mastery_clamped(self, temp_storage):
        row = skill_state.upsert_skill("u1", "Spanish", "speaking", mastery=1.5)
        assert row["mastery"] == 1.0


class TestAssessments:
    def test_record_and_latest(self, temp_storage):
        assessments.record_assessment(
            "u1", "Spanish", skill="speaking", cefr="B1", confidence=0.7, sample_size=100
        )
        latest = assessments.latest_assessment("u1", "Spanish", skill="speaking")
        assert latest is not None
        assert latest["cefr"] == "B1"
        assert latest["sample_size"] == 100


class TestExperiments:
    def test_assignment_is_stable(self, temp_storage):
        experiments.create_experiment("adaptive_vs_baseline", ["control", "treatment"])
        v1 = experiments.assign("adaptive_vs_baseline", "u1")
        v2 = experiments.assign("adaptive_vs_baseline", "u1")
        assert v1 == v2
        assert v1 in {"control", "treatment"}

    def test_get_assignment(self, temp_storage):
        experiments.create_experiment("exp", ["a", "b"])
        assert experiments.get_assignment("exp", "u1") is None
        experiments.assign("exp", "u1")
        assert experiments.get_assignment("exp", "u1") in {"a", "b"}


class TestOutcomes:
    def test_record_uses_existing_assignment_by_default(self, temp_storage):
        experiments.create_experiment("exp", ["control", "treatment"])
        variant = experiments.assign("exp", "u1")
        experiments.record_outcome("exp", "u1", "pre_test", "overall_cefr_ordinal", 1.0)
        rows = experiments.get_outcomes("exp", user_id="u1")
        assert len(rows) == 1
        assert rows[0]["variant"] == variant
        assert rows[0]["measurement_point"] == "pre_test"
        assert rows[0]["value"] == 1.0
        assert rows[0]["payload"] == {}

    def test_record_without_assignment_raises(self, temp_storage):
        experiments.create_experiment("exp", ["a", "b"])
        with pytest.raises(ValueError, match="no variant assignment"):
            experiments.record_outcome("exp", "unassigned-user", "pre_test", "metric", 1.0)

    def test_record_accepts_explicit_variant_without_prior_assignment(self, temp_storage):
        experiments.create_experiment("exp", ["a", "b"])
        experiments.record_outcome("exp", "u1", "pre_test", "metric", 2.0, variant="a")
        rows = experiments.get_outcomes("exp", user_id="u1")
        assert rows[0]["variant"] == "a"

    def test_get_outcomes_filters_by_measurement_point(self, temp_storage):
        experiments.create_experiment("exp", ["a"])
        experiments.assign("exp", "u1")
        experiments.record_outcome("exp", "u1", "pre_test", "metric", 1.0)
        experiments.record_outcome("exp", "u1", "immediate_post", "metric", 2.0)
        pre = experiments.get_outcomes("exp", measurement_point="pre_test")
        assert len(pre) == 1
        assert pre[0]["value"] == 1.0

    def test_get_outcomes_ordered_oldest_first(self, temp_storage):
        experiments.create_experiment("exp", ["a"])
        experiments.assign("exp", "u1")
        for point in ("pre_test", "immediate_post", "delayed_7d"):
            experiments.record_outcome("exp", "u1", point, "metric", 1.0)
        rows = experiments.get_outcomes("exp", user_id="u1")
        assert [r["measurement_point"] for r in rows] == [
            "pre_test",
            "immediate_post",
            "delayed_7d",
        ]

    def test_payload_round_trips(self, temp_storage):
        experiments.create_experiment("exp", ["a"])
        experiments.assign("exp", "u1")
        experiments.record_outcome(
            "exp", "u1", "pre_test", "metric", 1.0, payload={"cefr": "B1", "skills": ["grammar"]}
        )
        row = experiments.get_outcomes("exp", user_id="u1")[0]
        assert row["payload"] == {"cefr": "B1", "skills": ["grammar"]}

    def test_summarize_outcomes_means_by_variant_and_point(self, temp_storage):
        experiments.create_experiment("exp", ["control", "treatment"])
        experiments.record_outcome(
            "exp", "u1", "pre_test", "overall_cefr_ordinal", 1.0, variant="control"
        )
        experiments.record_outcome(
            "exp", "u2", "pre_test", "overall_cefr_ordinal", 3.0, variant="control"
        )
        experiments.record_outcome(
            "exp", "u3", "pre_test", "overall_cefr_ordinal", 2.0, variant="treatment"
        )
        summary = experiments.summarize_outcomes("exp", "overall_cefr_ordinal")
        assert summary["control"]["pre_test"] == {"n": 2, "mean": 2.0}
        assert summary["treatment"]["pre_test"] == {"n": 1, "mean": 2.0}

    def test_summarize_outcomes_ignores_other_metrics(self, temp_storage):
        experiments.create_experiment("exp", ["a"])
        experiments.record_outcome("exp", "u1", "pre_test", "metric_a", 1.0, variant="a")
        experiments.record_outcome("exp", "u1", "pre_test", "metric_b", 99.0, variant="a")
        summary = experiments.summarize_outcomes("exp", "metric_a")
        assert summary == {"a": {"pre_test": {"n": 1, "mean": 1.0}}}

    def test_summarize_outcomes_empty_when_no_data(self, temp_storage):
        assert experiments.summarize_outcomes("no-such-experiment", "metric") == {}


class TestModelRuns:
    def test_persist_and_query(self, temp_storage):
        from src.llm.telemetry import ModelRun

        model_runs.record_run(
            ModelRun(provider="claude", tier="primary", model="claude-sonnet-4", output_tokens=50)
        )
        runs = model_runs.get_runs()
        assert runs
        assert runs[0]["provider"] == "claude"

    def test_telemetry_sink_persists(self, temp_storage):
        from src.llm import telemetry
        from src.llm.telemetry import ModelRun

        telemetry.clear_sinks()
        model_runs.enable_persistence()
        telemetry.record(ModelRun(provider="gemini", tier="fast", output_tokens=10))
        telemetry.clear_sinks()
        assert any(r["provider"] == "gemini" for r in model_runs.get_runs())


class TestResumeFlow:
    async def test_start_learn_quit_restart_resume(self, temp_storage, monkeypatch):
        """End-to-end: a user learns, the session persists, and a later session
        surfaces a review generated from prior evidence."""
        from datetime import UTC, datetime, timedelta

        from src.memory import vocabulary_db
        from src.orchestrator import lifecycle

        # Avoid FSRS scheduling variance: schedule the word as already due.
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()

        # --- Session 1: build state, "learn" a word, finalize. ---
        state = lifecycle.build_initial_state("learner", "Spanish", session_id="sess-1")
        assert sessions.get_session("sess-1")["status"] == "active"

        vocabulary_db.upsert_word(
            "learner", "Spanish", "mesa", translation="table", next_review=past
        )
        state["new_vocabulary"] = []  # already stored directly above
        state["messages"] = [{"role": "user", "content": "hola"}]
        lifecycle.persist_session(state)

        # Session 1 marked completed.
        assert sessions.get_session("sess-1")["status"] == "completed"

        # --- Session 2 (restart): due review surfaces from prior data. ---
        state2 = lifecycle.build_initial_state("learner", "Spanish", session_id="sess-2")
        due_words = {r["word"] for r in state2["pending_reviews"]}
        assert "mesa" in due_words
