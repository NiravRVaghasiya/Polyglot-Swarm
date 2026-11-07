"""Shared SQLite connection helper for the memory layer.

All relational stores (vocabulary, grammar errors, sessions, analytics) live in
a single SQLite database at ``settings.db_path``. This module centralizes
connection creation so every store applies the same pragmas and row factory.
"""

from __future__ import annotations

import functools
import sqlite3
from collections.abc import Callable, Iterator
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


# --- schema setup, once per process per database (ADR-0035) -----------------
# Every store used to re-run its CREATE TABLE IF NOT EXISTS scripts (and the
# migration runner) on every call: ~10 times and 60+ connections per review
# request, about 70% of its latency. Schema setup is idempotent, so it only
# has to happen once per process for a given database file.
_ready: set[tuple[str, str]] = set()


def once_per_database(fn: Callable[[], None]) -> Callable[[], None]:
    """Run a schema-ensuring function once per process per database file.

    Re-runs if the database file disappeared (tests, a deleted file) or after
    :func:`reset_schema_cache` (a restore may bring back an older schema).
    """

    @functools.wraps(fn)
    def wrapper() -> None:
        path = _db_path()
        key = (f"{fn.__module__}.{fn.__qualname__}", str(path))
        if key in _ready and path.exists():
            return
        fn()
        _ready.add(key)

    return wrapper


def reset_schema_cache() -> None:
    """Forget which databases were set up (after a restore)."""
    _ready.clear()
