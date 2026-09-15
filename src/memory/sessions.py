"""Session lifecycle store — first-class, queryable session records.

Distinct from ``learning_sessions`` (a per-session *metrics summary*), this
tracks the lifecycle of each session: when it started, its mode/scenario, and
whether it completed or was abandoned. Keyed by ``session_id`` (the same value
used as the LangGraph checkpoint thread id), so a resumed session and its
persisted graph state line up.

This is what makes "quit, restart, authenticate, resume" auditable: the API and
CLI can list a user's active/most-recent sessions and continue them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_session(
    session_id: str,
    user_id: str,
    language: str,
    *,
    mode: str = "conversation",
    scenario_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Record the start of a session (idempotent on ``session_id``)."""
    init_all()
    when = started_at or _now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, user_id, language, mode, scenario_id,
                                  status, started_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id = excluded.user_id,
                language = excluded.language,
                mode = excluded.mode,
                scenario_id = excluded.scenario_id
            """,
            (session_id, user_id, language, mode, scenario_id, when),
        )
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row)


def end_session(
    session_id: str,
    *,
    status: str = "completed",
    ended_at: str | None = None,
) -> None:
    """Mark a session completed (or abandoned)."""
    init_all()
    when = ended_at or _now()
    with get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET status=?, ended_at=? WHERE session_id=?",
            (status, when, session_id),
        )


def get_session(session_id: str) -> dict[str, Any] | None:
    """Return a session record, or ``None`` if unknown."""
    init_all()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(
    user_id: str,
    language: str | None = None,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a user's sessions, most recent first."""
    init_all()
    clauses = ["user_id = ?"]
    params: list[Any] = [user_id]
    if language is not None:
        clauses.append("language = ?")
        params.append(language)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = " AND ".join(clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM sessions WHERE {where} ORDER BY started_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def latest_resumable(user_id: str, language: str | None = None) -> dict[str, Any] | None:
    """Return the most recent still-active session for resume, if any."""
    active = list_sessions(user_id, language, status="active", limit=1)
    return active[0] if active else None


def delete_for_user(user_id: str) -> int:
    """Delete every session-lifecycle row for ``user_id`` (Phase 21 deletion)."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        return cursor.rowcount
