"""Persistence for evidence events (the ``evidence`` table).

Events are append-only: once written they are never mutated, which is what
makes them a trustworthy audit trail for how the learner model reached its
current beliefs. ``event_id`` is unique, so re-inserting the same event is a
no-op (idempotent replay).
"""

from __future__ import annotations

import json
from typing import Any

from src.evidence.events import LearningEvent
from src.memory.db import get_connection
from src.memory.schema import init_all


def record_event(event: LearningEvent) -> None:
    """Persist a single evidence event (idempotent on ``event_id``)."""
    record_events([event])


def record_events(events: list[LearningEvent]) -> int:
    """Persist a batch of events. Returns the number newly inserted."""
    if not events:
        return 0
    init_all()
    inserted = 0
    with get_connection() as conn:
        for e in events:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO evidence (
                    event_id, user_id, language, session_id, interaction_id,
                    event_type, skill, item_id, observed, expected, assessment,
                    confidence, source, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e.event_id,
                    e.user_id,
                    e.language,
                    e.session_id,
                    e.interaction_id,
                    e.event_type.value,
                    e.skill,
                    e.item_id,
                    e.observed,
                    e.expected,
                    e.assessment,
                    e.confidence,
                    e.source,
                    json.dumps(e.payload),
                    e.created_at,
                ),
            )
            inserted += cursor.rowcount
    return inserted


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("payload"), str):
        data["payload"] = json.loads(data["payload"])
    return data


def get_events(
    user_id: str,
    language: str | None = None,
    *,
    event_type: str | None = None,
    session_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return stored events for a user, most recent first, with optional filters."""
    init_all()
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if language is not None:
        clauses.append("language = ?")
        params.append(language)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    if session_id is not None:
        clauses.append("session_id = ?")
        params.append(session_id)
    where = " AND ".join(clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM evidence WHERE {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_events(user_id: str, language: str | None = None) -> int:
    """Return how many evidence events a user has."""
    init_all()
    with get_connection() as conn:
        if language is None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM evidence WHERE user_id=?", (user_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM evidence WHERE user_id=? AND language=?",
                (user_id, language),
            ).fetchone()
    return int(row["n"])


def delete_for_user(user_id: str) -> int:
    """Delete every evidence event for ``user_id`` (Phase 21 data deletion).

    Evidence is normally append-only (the whole point is a trustworthy audit
    trail of what was observed) — deletion is an explicit exception for the
    right-to-erasure case, not something the ordinary evidence pipeline does.
    """
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM evidence WHERE user_id=?", (user_id,))
        return cursor.rowcount
