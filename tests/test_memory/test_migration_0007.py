"""ADR-0031 migration 0007: additive evidence/LKM columns preserve legacy data.

Builds a real version-6 database (the schema before this change) with legacy
evidence, skill-state, and assessment rows, then upgrades it and checks that
every row survives unchanged, the new columns exist with safe defaults, and the
upgrade is idempotent.
"""

from __future__ import annotations

from src.memory import schema
from src.memory.db import get_connection


def _build_v6_database(monkeypatch) -> None:
    monkeypatch.setattr(schema, "_MIGRATIONS", schema._MIGRATIONS[:6])
    assert schema.run_migrations() == 6
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO evidence (event_id, user_id, language, session_id, interaction_id,
                event_type, skill, item_id, observed, expected, assessment, confidence,
                source, payload, created_at)
            VALUES ('legacy-1', 'old-user', 'Spanish', 's-old', NULL, 'GRAMMAR_ERROR',
                'grammar', 'ser_vs_estar', 'soy cansado', 'estoy cansado', 'incorrect',
                0.85, 'session-extractor-v1', '{"severity": "moderate"}',
                '2026-09-01T10:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO skill_states (user_id, language, skill, mastery, uncertainty,
                sample_size, updated_at)
            VALUES ('old-user', 'Spanish', 'grammar', 0.0, 0.89, 1,
                '2026-09-01T10:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO assessments (user_id, language, skill, cefr, score, confidence,
                sample_size, method, created_at)
            VALUES ('old-user', 'Spanish', NULL, 'A2', NULL, 0.0, 0, 'cefr-profile-v1',
                '2026-09-01T10:00:00+00:00')
            """
        )


class TestMigration0007:
    def test_fresh_database_reaches_version_7(self, temp_storage):
        assert schema.run_migrations() == schema.SCHEMA_VERSION == 7

    def test_upgrade_from_v6_preserves_legacy_rows(self, temp_storage, monkeypatch):
        full = list(schema._MIGRATIONS)
        _build_v6_database(monkeypatch)
        monkeypatch.setattr(schema, "_MIGRATIONS", full)

        assert schema.run_migrations() == 7

        with get_connection() as conn:
            ev = dict(conn.execute("SELECT * FROM evidence WHERE event_id='legacy-1'").fetchone())
            ss = dict(conn.execute("SELECT * FROM skill_states").fetchone())
            asm = dict(conn.execute("SELECT * FROM assessments").fetchone())
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

        # Legacy values untouched.
        assert ev["observed"] == "soy cansado"
        assert ev["confidence"] == 0.85
        assert ev["created_at"] == "2026-09-01T10:00:00+00:00"
        assert ss["mastery"] == 0.0 and ss["sample_size"] == 1
        assert asm["cefr"] == "A2" and asm["method"] == "cefr-profile-v1"

        # New columns exist with safe defaults for legacy rows.
        assert ev["schema_version"] == 1
        assert ev["difficulty"] is None
        assert ev["difficulty_basis"] == "unknown"
        assert ev["fingerprint"] is None  # computed on read, never back-filled
        assert ss["method"] is None and ss["status"] is None
        assert asm["status"] is None

        assert {"evidence_supersessions", "lkm_processing_runs", "mastery_updates"} <= tables

    def test_upgrade_is_idempotent(self, temp_storage, monkeypatch):
        full = list(schema._MIGRATIONS)
        _build_v6_database(monkeypatch)
        monkeypatch.setattr(schema, "_MIGRATIONS", full)
        schema.run_migrations()
        # Re-running the migration body directly must not fail or duplicate.
        with get_connection() as conn:
            schema._migration_0007_evidence_lkm_v2(conn)
        assert schema.run_migrations() == 7
        with get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1

    def test_legacy_evidence_reads_back_with_defaults(self, temp_storage, monkeypatch):
        from src.evidence import store

        full = list(schema._MIGRATIONS)
        _build_v6_database(monkeypatch)
        monkeypatch.setattr(schema, "_MIGRATIONS", full)

        rows = store.active_events("old-user", "Spanish")
        assert len(rows) == 1
        row = rows[0]
        assert row["difficulty_basis"] == "unknown"
        assert row["fingerprint"]  # derived on read
        assert row["payload"] == {"severity": "moderate"}

    def test_legacy_evidence_replays_into_v2_model(self, temp_storage, monkeypatch):
        from src.learner import get_knowledge_model

        full = list(schema._MIGRATIONS)
        _build_v6_database(monkeypatch)
        monkeypatch.setattr(schema, "_MIGRATIONS", full)

        estimates = get_knowledge_model().recompute("old-user", "Spanish", trigger="migration")
        grammar = estimates["grammar"]
        # One legacy error is evidence, but nowhere near enough for a level.
        assert grammar.status == "insufficient_evidence"
        assert grammar.cefr is None
        assert grammar.raw_count == 1
