"""Collocation store — multi-word lexical units as first-class objects.

Language competence is not just single-word knowledge. Fixed collocations like
"tomar una decisión", "hacer una pregunta", "tener ganas de" are learned as
units and are a major quality upgrade (Phase 5). This store tracks them like
vocabulary — seen/produced counters, a mastery score, and FSRS scheduling —
keyed by ``(user_id, language, phrase)``.
"""

from __future__ import annotations

import json
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    if data.get("card_state"):
        data["card_state"] = json.loads(data["card_state"])
    return data


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


def delete_for_user(user_id: str) -> int:
    """Delete every collocation row for ``user_id`` (Phase 21 data deletion)."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM collocations WHERE user_id=?", (user_id,))
        return cursor.rowcount
