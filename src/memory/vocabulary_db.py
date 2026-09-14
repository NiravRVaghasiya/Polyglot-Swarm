"""SQLite vocabulary store — per-user personal lexicon with SRS metadata.

Persists every word a learner has encountered, keyed by ``(user_id, language,
word)``. Each row carries usage counters, contextual example sentences, and the
serialized FSRS card state plus its ``next_review`` timestamp so the SRS agent
can schedule reviews across sessions.

This is the persistent backing store behind the in-conversation Vocabulary
Agent: words extracted during a turn are upserted here, and due items are read
back at the start of later sessions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vocabulary (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT NOT NULL,
    language       TEXT NOT NULL,
    word           TEXT NOT NULL,
    translation    TEXT DEFAULT '',
    pos            TEXT DEFAULT '',
    cefr_level     TEXT DEFAULT '',
    contexts       TEXT DEFAULT '[]',   -- JSON list of example sentences
    times_seen     INTEGER DEFAULT 0,
    times_correct  INTEGER DEFAULT 0,
    times_incorrect INTEGER DEFAULT 0,
    card_state     TEXT,                -- JSON serialized FSRS card
    next_review    TEXT,                -- ISO8601 datetime
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE(user_id, language, word)
);
CREATE INDEX IF NOT EXISTS idx_vocab_user_lang ON vocabulary(user_id, language);
CREATE INDEX IF NOT EXISTS idx_vocab_due ON vocabulary(user_id, next_review);
"""


def init_db() -> None:
    """Create the vocabulary table and indexes if they do not exist."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["contexts"] = json.loads(data.get("contexts") or "[]")
    if data.get("card_state"):
        data["card_state"] = json.loads(data["card_state"])
    return data


def upsert_word(
    user_id: str,
    language: str,
    word: str,
    *,
    translation: str = "",
    pos: str = "",
    cefr_level: str = "",
    context: str | None = None,
    card_state: dict[str, Any] | None = None,
    next_review: str | None = None,
    seen: bool = True,
) -> dict[str, Any]:
    """Insert a new word or update an existing one for this user.

    On conflict (same user/language/word) the counters accumulate, a new
    context sentence is appended (deduplicated), and metadata fields are updated
    when non-empty values are supplied.

    Returns the resulting row as a dict.
    """
    init_db()
    now = _now()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM vocabulary WHERE user_id=? AND language=? AND word=?",
            (user_id, language, word),
        ).fetchone()

        if existing is None:
            contexts = [context] if context else []
            conn.execute(
                """
                INSERT INTO vocabulary (
                    user_id, language, word, translation, pos, cefr_level,
                    contexts, times_seen, card_state, next_review,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, language, word, translation, pos, cefr_level,
                    json.dumps(contexts), 1 if seen else 0,
                    json.dumps(card_state) if card_state else None,
                    next_review, now, now,
                ),
            )
        else:
            contexts = json.loads(existing["contexts"] or "[]")
            if context and context not in contexts:
                contexts.append(context)

            conn.execute(
                """
                UPDATE vocabulary SET
                    translation = COALESCE(NULLIF(?, ''), translation),
                    pos         = COALESCE(NULLIF(?, ''), pos),
                    cefr_level  = COALESCE(NULLIF(?, ''), cefr_level),
                    contexts    = ?,
                    times_seen  = times_seen + ?,
                    card_state  = COALESCE(?, card_state),
                    next_review = COALESCE(?, next_review),
                    updated_at  = ?
                WHERE user_id=? AND language=? AND word=?
                """,
                (
                    translation, pos, cefr_level,
                    json.dumps(contexts), 1 if seen else 0,
                    json.dumps(card_state) if card_state else None,
                    next_review, now,
                    user_id, language, word,
                ),
            )

        row = conn.execute(
            "SELECT * FROM vocabulary WHERE user_id=? AND language=? AND word=?",
            (user_id, language, word),
        ).fetchone()

    return _row_to_dict(row)


def record_review_outcome(
    user_id: str,
    language: str,
    word: str,
    *,
    correct: bool,
    card_state: dict[str, Any] | None = None,
    next_review: str | None = None,
) -> None:
    """Update correctness counters and scheduling after a review."""
    init_db()
    column = "times_correct" if correct else "times_incorrect"
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE vocabulary SET
                {column} = {column} + 1,
                card_state = COALESCE(?, card_state),
                next_review = COALESCE(?, next_review),
                updated_at = ?
            WHERE user_id=? AND language=? AND word=?
            """,
            (
                json.dumps(card_state) if card_state else None,
                next_review, _now(), user_id, language, word,
            ),
        )


def get_all_for_user(user_id: str, language: str | None = None) -> list[dict[str, Any]]:
    """Return all vocabulary rows for a user, optionally filtered by language."""
    init_db()
    with get_connection() as conn:
        if language is None:
            rows = conn.execute(
                "SELECT * FROM vocabulary WHERE user_id=? ORDER BY word",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vocabulary WHERE user_id=? AND language=? ORDER BY word",
                (user_id, language),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_due(
    user_id: str,
    language: str | None = None,
    *,
    now: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return items whose ``next_review`` is due (<= now), most overdue first."""
    init_db()
    cutoff = now or _now()
    with get_connection() as conn:
        params: tuple[Any, ...]
        query = (
            "SELECT * FROM vocabulary "
            "WHERE user_id=? AND next_review IS NOT NULL AND next_review <= ?"
        )
        params = (user_id, cutoff)
        if language is not None:
            query += " AND language=?"
            params = (user_id, cutoff, language)
        query += " ORDER BY next_review ASC LIMIT ?"
        params = (*params, limit)
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_for_user(user_id: str, language: str | None = None) -> int:
    """Return how many distinct words a user has stored."""
    init_db()
    with get_connection() as conn:
        if language is None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM vocabulary WHERE user_id=?",
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM vocabulary WHERE user_id=? AND language=?",
                (user_id, language),
            ).fetchone()
    return int(row["n"])
