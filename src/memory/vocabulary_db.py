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
    -- Phase 5: multi-dimensional mastery (0.0 .. 1.0 each). A word is not
    -- simply known/unknown; recognition/production/listening/spelling are
    -- tracked separately.
    recognition    REAL DEFAULT 0.0,
    production     REAL DEFAULT 0.0,
    listening      REAL DEFAULT 0.0,
    spelling       REAL DEFAULT 0.0,
    -- Phase 5: lexical metadata + production history.
    register       TEXT DEFAULT '',     -- neutral | formal | informal | slang | ...
    frequency_rank INTEGER,             -- corpus frequency rank (lower = commoner)
    first_seen     TEXT,                -- ISO8601: first time encountered
    first_produced TEXT,                -- ISO8601: first time the learner produced it
    successful_productions INTEGER DEFAULT 0,
    failed_productions     INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE(user_id, language, word)
);
CREATE INDEX IF NOT EXISTS idx_vocab_user_lang ON vocabulary(user_id, language);
CREATE INDEX IF NOT EXISTS idx_vocab_due ON vocabulary(user_id, next_review);
"""

# The multi-dimensional mastery dimensions tracked per word (Phase 5).
VOCAB_DIMENSIONS = ("recognition", "production", "listening", "spelling")

# Columns added by the v3 migration, for existing databases. Kept in sync with
# the _SCHEMA above; the migration adds any that are missing.
_PHASE5_COLUMNS: dict[str, str] = {
    "recognition": "REAL DEFAULT 0.0",
    "production": "REAL DEFAULT 0.0",
    "listening": "REAL DEFAULT 0.0",
    "spelling": "REAL DEFAULT 0.0",
    "register": "TEXT DEFAULT ''",
    "frequency_rank": "INTEGER",
    "first_seen": "TEXT",
    "first_produced": "TEXT",
    "successful_productions": "INTEGER DEFAULT 0",
    "failed_productions": "INTEGER DEFAULT 0",
}


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
                    user_id,
                    language,
                    word,
                    translation,
                    pos,
                    cefr_level,
                    json.dumps(contexts),
                    1 if seen else 0,
                    json.dumps(card_state) if card_state else None,
                    next_review,
                    now,
                    now,
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
                    translation,
                    pos,
                    cefr_level,
                    json.dumps(contexts),
                    1 if seen else 0,
                    json.dumps(card_state) if card_state else None,
                    next_review,
                    now,
                    user_id,
                    language,
                    word,
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
                next_review,
                _now(),
                user_id,
                language,
                word,
            ),
        )


def record_dimension(
    user_id: str,
    language: str,
    word: str,
    dimension: str,
    *,
    success: bool,
    weight: float = 0.3,
    at: str | None = None,
) -> dict[str, Any] | None:
    """Update one mastery dimension for a word from an observation.

    ``dimension`` is one of :data:`VOCAB_DIMENSIONS`. The new score is an
    exponential moving average toward 1.0 (success) or 0.0 (failure) with the
    given ``weight`` — a simple, transparent update that is monotonic in
    evidence and bounded to [0, 1]. Production observations also bump the
    ``successful_productions``/``failed_productions`` counters and stamp
    ``first_produced`` on the first success.

    Returns the updated row, or ``None`` if the word is not stored yet (the
    caller should upsert it first).
    """
    if dimension not in VOCAB_DIMENSIONS:
        raise ValueError(f"unknown vocabulary dimension: {dimension!r}")
    init_db()
    when = at or _now()
    target = 1.0 if success else 0.0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM vocabulary WHERE user_id=? AND language=? AND word=?",
            (user_id, language, word),
        ).fetchone()
        if row is None:
            return None

        current = row[dimension] if row[dimension] is not None else 0.0
        updated = round(current + weight * (target - current), 4)
        updated = max(0.0, min(1.0, updated))

        sets = [f"{dimension} = ?", "updated_at = ?"]
        params: list[Any] = [updated, when]

        if dimension == "production":
            if success:
                sets.append("successful_productions = successful_productions + 1")
                if row["first_produced"] is None:
                    sets.append("first_produced = ?")
                    params.append(when)
            else:
                sets.append("failed_productions = failed_productions + 1")

        conn.execute(
            f"UPDATE vocabulary SET {', '.join(sets)} WHERE user_id=? AND language=? AND word=?",
            (*params, user_id, language, word),
        )
        out = conn.execute(
            "SELECT * FROM vocabulary WHERE user_id=? AND language=? AND word=?",
            (user_id, language, word),
        ).fetchone()
    return _row_to_dict(out)


def set_metadata(
    user_id: str,
    language: str,
    word: str,
    *,
    register: str | None = None,
    frequency_rank: int | None = None,
    first_seen: str | None = None,
) -> None:
    """Set lexical metadata (register, frequency rank, first_seen) if provided.

    Only non-``None`` fields are written; ``first_seen`` is set only if not
    already present, so the earliest observation wins.
    """
    init_db()
    sets: list[str] = ["updated_at = ?"]
    params: list[Any] = [_now()]
    if register is not None:
        sets.append("register = ?")
        params.append(register)
    if frequency_rank is not None:
        sets.append("frequency_rank = ?")
        params.append(frequency_rank)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE vocabulary SET {', '.join(sets)} WHERE user_id=? AND language=? AND word=?",
            (*params, user_id, language, word),
        )
        if first_seen is not None:
            conn.execute(
                "UPDATE vocabulary SET first_seen = COALESCE(first_seen, ?) "
                "WHERE user_id=? AND language=? AND word=?",
                (first_seen, user_id, language, word),
            )


def mastery_summary(row: dict[str, Any]) -> dict[str, float]:
    """Return the per-dimension mastery scores for a vocabulary row."""
    return {dim: float(row.get(dim) or 0.0) for dim in VOCAB_DIMENSIONS}


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


def delete_for_user(user_id: str) -> int:
    """Delete every vocabulary row for ``user_id`` (Phase 21 data deletion).

    Returns the number of rows removed.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM vocabulary WHERE user_id=?", (user_id,))
        return cursor.rowcount
