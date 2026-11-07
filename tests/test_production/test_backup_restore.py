"""Backup, verification, restore drill, retention and migration safety (R4, R16)."""

from __future__ import annotations

import sqlite3

import pytest

from src.api import auth
from src.config import settings
from src.memory import schema
from src.memory.db import get_connection
from src.ops import backup


@pytest.fixture
def data(temp_storage):
    schema.init_all()
    auth.register("drill-user", "correct-horse-1")
    media = temp_storage / "media" / "u1"
    media.mkdir(parents=True)
    (media / "clip.wav").write_bytes(b"RIFF....fake")
    return temp_storage


def _users() -> int:
    with get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])


class TestBackupSets:
    def test_a_backup_set_is_complete_and_verified(self, data):
        path = backup.create_backup_set(label="nightly")
        manifest = backup.verify_backup_set(path)
        assert manifest["integrity"] == "ok"
        assert manifest["schema_version"] == schema.SCHEMA_VERSION
        assert manifest["row_counts"]["users"] == 1
        assert "media/u1/clip.wav" in manifest["files"]
        assert backup.list_backup_sets() == [path]
        assert backup.last_verified_backup_time() is not None

    def test_tampering_is_detected(self, data):
        path = backup.create_backup_set()
        (path / "media" / "u1" / "clip.wav").write_bytes(b"changed")
        with pytest.raises(backup.BackupError, match="checksum"):
            backup.verify_backup_set(path)

    def test_a_corrupt_database_never_becomes_a_listed_backup(self, data, monkeypatch):
        monkeypatch.setattr(
            backup, "_db_facts", lambda db: {"integrity": "corrupt", "schema_version": 0,
                                             "row_counts": {}}
        )  # fmt: skip
        with pytest.raises(backup.BackupError):
            backup.create_backup_set()
        assert backup.list_backup_sets() == []

    def test_retention_keeps_the_newest(self, data):
        made = [backup.create_backup_set(label=f"n{i}") for i in range(4)]
        removed = backup.prune_backups(keep=2)
        assert set(removed) == set(made[:2])
        assert backup.list_backup_sets() == sorted(made[2:], reverse=True)


class TestRestoreDrill:
    def test_restore_recovers_lost_data(self, data):
        """Drill: back up, lose data, restore, verify counts and files."""
        good = backup.create_backup_set(label="drill")
        with get_connection() as conn:  # the incident: accounts lost
            conn.execute("DELETE FROM auth_tokens")
            conn.execute("DELETE FROM users")
        (data / "media" / "u1" / "clip.wav").unlink()
        assert _users() == 0

        manifest = backup.restore_backup_set(good)
        assert _users() == manifest["row_counts"]["users"] == 1
        assert (data / "media" / "u1" / "clip.wav").read_bytes() == b"RIFF....fake"
        # A safety backup of the pre-restore state was taken first.
        assert any(p.name.endswith("-pre-restore") for p in backup.list_backup_sets())
        assert auth.login("drill-user", "correct-horse-1")

    def test_a_bad_backup_is_refused_and_live_data_untouched(self, data):
        path = backup.create_backup_set()
        (path / backup.DB_NAME).write_bytes(b"not a database")
        with pytest.raises(backup.BackupError):
            backup.restore_backup_set(path)
        assert _users() == 1


class TestMigrationSafety:
    def test_upgrading_an_existing_database_backs_it_up_first(self, temp_storage):
        schema.init_all()
        with get_connection() as conn:  # simulate a deployment still on schema v9
            conn.execute("DROP TABLE active_sessions")
            conn.execute("DROP TABLE llm_usage_daily")
            conn.execute("DROP TABLE idempotency_keys")
            conn.execute("PRAGMA user_version = 9")
        assert schema.run_migrations() == schema.SCHEMA_VERSION
        sets = backup.list_backup_sets()
        assert sets and sets[0].name.endswith("pre-migration-v9")
        assert backup.verify_backup_set(sets[0])["schema_version"] == 9
        with get_connection() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert {"active_sessions", "llm_usage_daily", "idempotency_keys"} <= tables

    def test_a_fresh_database_needs_no_backup(self, temp_storage):
        schema.init_all()
        assert backup.list_backup_sets() == []

    def test_rollback_is_restoring_the_pre_migration_backup(self, temp_storage):
        schema.init_all()
        with get_connection() as conn:
            conn.execute("PRAGMA user_version = 9")
        schema.run_migrations()
        pre = backup.list_backup_sets()[0]
        backup.restore_backup_set(pre)
        conn = sqlite3.connect(settings.db_path)
        try:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
        finally:
            conn.close()
