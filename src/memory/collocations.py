"""Collocation store — multi-word lexical units as first-class objects.

Language competence is not just single-word knowledge. Fixed collocations like
"tomar una decisión", "hacer una pregunta", "tener ganas de" are learned as
units and are a major quality upgrade (Phase 5). This store tracks them like
vocabulary — seen/produced counters, a mastery score, and FSRS scheduling —
keyed by ``(user_id, language, phrase)``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    if data.get("card_state"):
        data["card_state"] = json.loads(data["card_state"])
    return data


def upsert_collocation(
    user_id: str,
    language: str,
    phrase: str,
    *,
    translation: str = "",
    pattern: str = "",
    cefr_level: str = "",
    register: str = "",
    produced: bool = False,
    card_state: dict[str, Any] | None = None,
    next_review: str | None = None,
) -> dict[str, Any]:
    """Insert or update a collocation. Returns the resulting row.

    On conflict, counters accumulate (``times_seen`` always; ``times_produced``
    when ``produced``), and non-empty metadata fields are updated.
    """
    init_all()
    now = _now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM collocations WHERE user_id=? AND language=? AND phrase=?",
            (user_id, language, phrase),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO collocations (
                    user_id, language, phrase, translation, pattern, cefr_level,
                    register, times_seen, times_produced, mastery, card_state,
                    next_review, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 0.0, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    language,
                    phrase,
                    translation,
                    pattern,
                    cefr_level,
                    register,
                    1 if produced else 0,
                    json.dumps(card_state) if card_state else None,
                    next_review,
                    now,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE collocations SET
                    translation = COALESCE(NULLIF(?, ''), translation),
                    pattern     = COALESCE(NULLIF(?, ''), pattern),
                    cefr_level  = COALESCE(NULLIF(?, ''), cefr_level),
                    register    = COALESCE(NULLIF(?, ''), register),
                    times_seen  = times_seen + 1,
                    times_produced = times_produced + ?,
                    card_state  = COALESCE(?, card_state),
                    next_review = COALESCE(?, next_review),
                    updated_at  = ?
                WHERE user_id=? AND language=? AND phrase=?
                """,
                (
                    translation,
                    pattern,
                    cefr_level,
                    register,
                    1 if produced else 0,
                    json.dumps(card_state) if card_state else None,
                    next_review,
                    now,
                    user_id,
                    language,
                    phrase,
                ),
            )

        row = conn.execute(
            "SELECT * FROM collocations WHERE user_id=? AND language=? AND phrase=?",
            (user_id, language, phrase),
        ).fetchone()
    return _row_to_dict(row)


def get_all_for_user(user_id: str, language: str | None = None) -> list[dict[str, Any]]:
    """Return a user's collocations, optionally filtered by language."""
    init_all()
    with get_connection() as conn:
        if language is None:
            rows = conn.execute(
                "SELECT * FROM collocations WHERE user_id=? ORDER BY phrase", (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM collocations WHERE user_id=? AND language=? ORDER BY phrase",
                (user_id, language),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_for_user(user_id: str, language: str | None = None) -> int:
    """Return how many distinct collocations a user has stored."""
    init_all()
    with get_connection() as conn:
        if language is None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM collocations WHERE user_id=?", (user_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM collocations WHERE user_id=? AND language=?",
                (user_id, language),
            ).fetchone()
    return int(row["n"])


def delete_for_user(user_id: str) -> int:
    """Delete every collocation row for ``user_id`` (Phase 21 data deletion)."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM collocations WHERE user_id=?", (user_id,))
        return cursor.rowcount
