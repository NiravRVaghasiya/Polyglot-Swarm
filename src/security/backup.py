"""SQLite database backups.

Uses SQLite's own online backup API (via the stdlib ``sqlite3`` module's
``Connection.backup()``), which is safe to run against a live database — it
does not require exclusive access or stopping writers, unlike a naive file
copy. Backups are named with a timestamp so :func:`list_backups` can show them
in order and a retention policy (if ever added) has an unambiguous sort key.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.config import settings

#: Suffix appended to every backup file (distinguishes them from the live DB
#: and from unrelated files in the same directory).
BACKUP_SUFFIX = ".backup.db"


def _backup_dir() -> Path:
    """Where backups are written: a ``backups/`` subdirectory of the data dir."""
    path = Path(settings.data_dir) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(*, label: str | None = None) -> Path:
    """Create a timestamped backup of the live SQLite database.

    Args:
        label: Optional short tag included in the filename (e.g. "pre-migration"),
            useful for distinguishing manual/scheduled backups from automatic ones.

    Returns:
        The path to the newly created backup file.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"-{label}" if label else ""
    dest = _backup_dir() / f"polyglot-{timestamp}{suffix}{BACKUP_SUFFIX}"

    source_path = Path(settings.db_path)
    source_path.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(str(source_path))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            source.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source.close()
    return dest


def list_backups() -> list[Path]:
    """Return existing backup files, most recent first (by filename, which
    sorts chronologically thanks to the ISO-8601-like timestamp prefix)."""
    if not _backup_dir().exists():
        return []
    return sorted(_backup_dir().glob(f"*{BACKUP_SUFFIX}"), reverse=True)
