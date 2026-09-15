"""Learning analytics + grammar error pattern store (SQLite).

Two concerns live here, both keyed by ``user_id``:

1. **Grammar error patterns** — a persistent model of each learner's specific
   weaknesses. Every time an error of a given type recurs, its frequency
   increments; once the learner stops making it, it can be marked mastered.
   This is the cross-session "error taxonomy" that distinguishes Polyglot Swarm
   from tools that forget between sessions.

2. **Learning sessions** — one row per completed session with the metrics used
   by the progress dashboards and the CEFR assessment agent.

Both tables share the single SQLite database from :mod:`src.memory.db`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection

_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    language        TEXT NOT NULL,
    error_type      TEXT NOT NULL,      -- e.g. "ser_vs_estar", "genitive_case"
    occurrences     INTEGER DEFAULT 0,
    last_occurrence TEXT,
    mastered        INTEGER DEFAULT 0,  -- boolean
    mastered_date   TEXT,
    UNIQUE(user_id, language, error_type)
);
CREATE INDEX IF NOT EXISTS idx_error_user_lang
    ON error_patterns(user_id, language);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                 TEXT NOT NULL,
    language                TEXT NOT NULL,
    session_type            TEXT,        -- conversation, drill, review, assessment
    duration_minutes        REAL DEFAULT 0,
    words_practiced         INTEGER DEFAULT 0,
    new_words_learned       INTEGER DEFAULT 0,
    grammar_errors          INTEGER DEFAULT 0,
    grammar_errors_corrected INTEGER DEFAULT 0,
    cefr_estimate           TEXT,
    timestamp               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_user_lang
    ON learning_sessions(user_id, language);
"""


def init_db() -> None:
    """Create the analytics tables if they do not exist."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- #
# Grammar error patterns
# --------------------------------------------------------------------------- #


def record_error(
    user_id: str,
    language: str,
    error_type: str,
    *,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Record one occurrence of a grammar error type, incrementing frequency.

    Re-occurring after being marked mastered resets the mastery flag, since the
    learner is evidently still making the mistake.

    Returns the resulting error-pattern row.
    """
    init_db()
    when = occurred_at or _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO error_patterns (
                user_id, language, error_type, occurrences, last_occurrence, mastered
            ) VALUES (?, ?, ?, 1, ?, 0)
            ON CONFLICT(user_id, language, error_type) DO UPDATE SET
                occurrences = occurrences + 1,
                last_occurrence = excluded.last_occurrence,
                mastered = 0,
                mastered_date = NULL
            """,
            (user_id, language, error_type, when),
        )
        row = conn.execute(
            "SELECT * FROM error_patterns WHERE user_id=? AND language=? AND error_type=?",
            (user_id, language, error_type),
        ).fetchone()
    return dict(row)


def mark_mastered(
    user_id: str,
    language: str,
    error_type: str,
    *,
    mastered_at: str | None = None,
) -> None:
    """Mark an error pattern as mastered (learner no longer makes it)."""
    init_db()
    when = mastered_at or _now()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE error_patterns
            SET mastered = 1, mastered_date = ?
            WHERE user_id=? AND language=? AND error_type=?
            """,
            (when, user_id, language, error_type),
        )


def get_error_patterns(
    user_id: str,
    language: str | None = None,
    *,
    include_mastered: bool = True,
) -> list[dict[str, Any]]:
    """Return a user's error patterns, most frequent first."""
    init_db()
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if language is not None:
        clauses.append("language = ?")
        params.append(language)
    if not include_mastered:
        clauses.append("mastered = 0")

    where = " AND ".join(clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM error_patterns WHERE {where} "
            "ORDER BY occurrences DESC, last_occurrence DESC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def top_weaknesses(
    user_id: str,
    language: str | None = None,
    *,
    limit: int = 5,
) -> list[str]:
    """Return the error_type names of a user's top unmastered weaknesses."""
    patterns = get_error_patterns(user_id, language, include_mastered=False)
    return [p["error_type"] for p in patterns[:limit]]


# --------------------------------------------------------------------------- #
# Learning sessions
# --------------------------------------------------------------------------- #


def log_session(
    user_id: str,
    language: str,
    *,
    session_type: str = "conversation",
    duration_minutes: float = 0.0,
    words_practiced: int = 0,
    new_words_learned: int = 0,
    grammar_errors: int = 0,
    grammar_errors_corrected: int = 0,
    cefr_estimate: str | None = None,
    timestamp: str | None = None,
) -> int:
    """Persist a completed session's metrics. Returns the new row id."""
    init_db()
    when = timestamp or _now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_sessions (
                user_id, language, session_type, duration_minutes,
                words_practiced, new_words_learned, grammar_errors,
                grammar_errors_corrected, cefr_estimate, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                language,
                session_type,
                duration_minutes,
                words_practiced,
                new_words_learned,
                grammar_errors,
                grammar_errors_corrected,
                cefr_estimate,
                when,
            ),
        )
        row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def get_sessions(
    user_id: str,
    language: str | None = None,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return a user's sessions, most recent first."""
    init_db()
    with get_connection() as conn:
        if language is None:
            rows = conn.execute(
                "SELECT * FROM learning_sessions WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM learning_sessions WHERE user_id=? AND language=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (user_id, language, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_for_user(user_id: str) -> dict[str, int]:
    """Delete every ``error_patterns`` and ``learning_sessions`` row for
    ``user_id`` (Phase 21 data deletion). Returns counts per table."""
    init_db()
    with get_connection() as conn:
        errors = conn.execute("DELETE FROM error_patterns WHERE user_id=?", (user_id,)).rowcount
        sessions = conn.execute(
            "DELETE FROM learning_sessions WHERE user_id=?", (user_id,)
        ).rowcount
    return {"error_patterns": errors, "learning_sessions": sessions}
