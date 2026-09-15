"""Phase 5 tests: multi-dimensional vocabulary mastery, collocations, and the
v3 schema migration."""

from __future__ import annotations

import pytest

from src.memory import collocations, schema, vocabulary_db


class TestMigrationV3:
    def test_schema_version_is_3(self, temp_storage):
        schema.init_all()
        # >= 3 rather than == 3: later phases (e.g. Phase 17's
        # session_interactions table) add further migrations, so the schema
        # version keeps growing. What this test protects is that the v3
        # (vocabulary dimensions) migration has been applied.
        assert schema.current_version() >= 3

    def test_vocabulary_has_dimension_columns(self, temp_storage):
        schema.init_all()
        from src.memory.db import get_connection

        with get_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(vocabulary)").fetchall()}
        assert {
            "recognition",
            "production",
            "listening",
            "spelling",
            "register",
            "frequency_rank",
            "first_seen",
            "first_produced",
            "successful_productions",
            "failed_productions",
        } <= cols

    def test_collocations_table_exists(self, temp_storage):
        schema.init_all()
        from src.memory.db import get_connection

        with get_connection() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "collocations" in tables


class TestVocabDimensions:
    def test_new_word_dimensions_default_zero(self, temp_storage):
        row = vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        assert vocabulary_db.mastery_summary(row) == {
            "recognition": 0.0,
            "production": 0.0,
            "listening": 0.0,
            "spelling": 0.0,
        }

    def test_record_dimension_moves_toward_one_on_success(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        r1 = vocabulary_db.record_dimension("u1", "Spanish", "mesa", "production", success=True)
        assert 0.0 < r1["production"] <= 1.0
        r2 = vocabulary_db.record_dimension("u1", "Spanish", "mesa", "production", success=True)
        assert r2["production"] > r1["production"]  # monotonic toward 1.0

    def test_record_dimension_moves_toward_zero_on_failure(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        vocabulary_db.record_dimension("u1", "Spanish", "mesa", "recognition", success=True)
        r = vocabulary_db.record_dimension("u1", "Spanish", "mesa", "recognition", success=True)
        after_fail = vocabulary_db.record_dimension(
            "u1", "Spanish", "mesa", "recognition", success=False
        )
        assert after_fail["recognition"] < r["recognition"]

    def test_production_counters_and_first_produced(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        row = vocabulary_db.record_dimension("u1", "Spanish", "mesa", "production", success=True)
        assert row["successful_productions"] == 1
        assert row["first_produced"] is not None
        row2 = vocabulary_db.record_dimension("u1", "Spanish", "mesa", "production", success=False)
        assert row2["failed_productions"] == 1

    def test_record_dimension_unknown_word_returns_none(self, temp_storage):
        assert (
            vocabulary_db.record_dimension("u1", "Spanish", "ghost", "production", success=True)
            is None
        )

    def test_invalid_dimension_raises(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        with pytest.raises(ValueError):
            vocabulary_db.record_dimension("u1", "Spanish", "mesa", "nonsense", success=True)

    def test_set_metadata(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        vocabulary_db.set_metadata(
            "u1",
            "Spanish",
            "mesa",
            register="informal",
            frequency_rank=42,
            first_seen="2020-01-01T00:00:00+00:00",
        )
        row = vocabulary_db.get_all_for_user("u1", "Spanish")[0]
        assert row["register"] == "informal"
        assert row["frequency_rank"] == 42
        assert row["first_seen"] == "2020-01-01T00:00:00+00:00"

    def test_first_seen_earliest_wins(self, temp_storage):
        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        vocabulary_db.set_metadata("u1", "Spanish", "mesa", first_seen="2020-01-01T00:00:00+00:00")
        vocabulary_db.set_metadata("u1", "Spanish", "mesa", first_seen="2021-01-01T00:00:00+00:00")
        row = vocabulary_db.get_all_for_user("u1", "Spanish")[0]
        assert row["first_seen"] == "2020-01-01T00:00:00+00:00"


class TestCollocations:
    def test_upsert_and_get(self, temp_storage):
        collocations.upsert_collocation(
            "u1",
            "Spanish",
            "tomar una decisión",
            translation="to make a decision",
            pattern="verb + noun",
            cefr_level="B1",
        )
        rows = collocations.get_all_for_user("u1", "Spanish")
        assert len(rows) == 1
        assert rows[0]["phrase"] == "tomar una decisión"
        assert rows[0]["times_seen"] == 1

    def test_accumulates_and_counts_production(self, temp_storage):
        collocations.upsert_collocation("u1", "Spanish", "hacer una pregunta")
        collocations.upsert_collocation("u1", "Spanish", "hacer una pregunta", produced=True)
        row = collocations.get_all_for_user("u1", "Spanish")[0]
        assert row["times_seen"] == 2
        assert row["times_produced"] == 1

    def test_count_for_user(self, temp_storage):
        collocations.upsert_collocation("u1", "Spanish", "tener ganas de")
        collocations.upsert_collocation("u1", "Spanish", "dar un paseo")
        assert collocations.count_for_user("u1", "Spanish") == 2


class TestPersistSessionUpdatesDimensions:
    def test_produced_word_bumps_production_dimension(self, temp_storage):
        from src.orchestrator.lifecycle import build_initial_state, persist_session

        state = build_initial_state("learner", "Spanish", session_id="sess-p5")
        state["messages"] = [{"role": "user", "content": "Quiero una mesa"}]
        state["new_vocabulary"] = [{"word": "mesa", "translation": "table", "pos": "noun"}]

        counts = persist_session(state)
        # Event count contract preserved (1 turn + 1 vocab = 2 events here).
        assert counts["events"] == 2

        row = vocabulary_db.get_all_for_user("learner", "Spanish")[0]
        assert row["word"] == "mesa"
        assert row["production"] > 0.0  # production dimension bumped from the event
        assert row["first_seen"] is not None
        assert row["successful_productions"] == 1
