"""`polyglot security backup|backups` are aliases of the verified ops backups."""

from __future__ import annotations

import sqlite3

from typer.testing import CliRunner

from src.cli import app
from src.ops import backup

runner = CliRunner()


class TestSecurityBackupAlias:
    def test_writes_a_verified_backup_set(self, temp_storage):
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        result = runner.invoke(app, ["security", "backup", "--label", "pre-migration"])
        assert result.exit_code == 0, result.output
        [path] = backup.list_backup_sets()
        assert path.name.endswith("-pre-migration")
        assert path.parent == backup.backup_root()
        backup.verify_backup_set(path)  # raises if the set is not restorable
        conn = sqlite3.connect(str(path / backup.DB_NAME))
        try:
            row = conn.execute("SELECT word FROM vocabulary WHERE user_id='u1'").fetchone()
        finally:
            conn.close()
        assert row == ("mesa",)

    def test_lists_the_same_sets_as_ops(self, temp_storage):
        assert "No backup sets" in runner.invoke(app, ["security", "backups"]).output
        assert runner.invoke(app, ["security", "backup", "--label", "one"]).exit_code == 0
        assert runner.invoke(app, ["security", "backup", "--label", "two"]).exit_code == 0
        listed = runner.invoke(app, ["security", "backups"]).output
        assert listed == runner.invoke(app, ["ops", "backups"]).output
        names = [p.name for p in backup.list_backup_sets()]
        assert len(names) == 2 and names[0].endswith("-two")  # newest first
        assert all(name in listed for name in names)

    def test_there_is_one_backup_module(self):
        import importlib.util

        assert importlib.util.find_spec("src.security.backup") is None
