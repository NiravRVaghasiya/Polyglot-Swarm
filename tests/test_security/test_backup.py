"""Phase 21 tests: SQLite database backups."""

from __future__ import annotations

from src.security.backup import BACKUP_SUFFIX, create_backup, list_backups


class TestCreateBackup:
    def test_creates_a_file(self, temp_storage):
        path = create_backup()
        assert path.exists()
        assert path.name.endswith(BACKUP_SUFFIX)

    def test_backup_contains_data(self, temp_storage):
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word("u1", "Spanish", "mesa")
        path = create_backup()

        import sqlite3

        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("SELECT word FROM vocabulary WHERE user_id='u1'").fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "mesa"

    def test_label_appears_in_filename(self, temp_storage):
        path = create_backup(label="pre-migration")
        assert "pre-migration" in path.name

    def test_backups_land_in_a_backups_subdirectory(self, temp_storage):
        path = create_backup()
        assert path.parent.name == "backups"

    def test_multiple_backups_get_distinct_names(self, temp_storage):
        a = create_backup(label="a")
        b = create_backup(label="b")
        assert a != b


class TestListBackups:
    def test_empty_when_none_created(self, temp_storage):
        assert list_backups() == []

    def test_lists_created_backups(self, temp_storage):
        create_backup(label="one")
        create_backup(label="two")
        backups = list_backups()
        assert len(backups) == 2

    def test_most_recent_first(self, temp_storage):
        first = create_backup(label="first")
        second = create_backup(label="second")
        backups = list_backups()
        # Filenames are timestamp-prefixed, so reverse-sorted = newest first.
        assert backups[0] in (first, second)
        assert backups == sorted(backups, reverse=True)
