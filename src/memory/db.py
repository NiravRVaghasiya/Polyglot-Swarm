"""Shared SQLite connection helper for the memory layer.

All relational stores (vocabulary, grammar errors, sessions, analytics) live in
a single SQLite database at ``settings.db_path``. This module centralizes
connection creation so every store applies the same pragmas and row factory.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from src.config import settings


def _db_path() -> Path:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults.

    - ``row_factory`` set to ``sqlite3.Row`` so callers get dict-like rows.
    - Foreign keys enforced.
    - WAL journal mode for better concurrent read/write behavior.
    """
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a connection that commits/rolls back and closes."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
