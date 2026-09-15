"""Session <-> interaction links (the correlation bridge for traces).

``model_runs`` records an ``interaction_id`` but no ``session_id`` (the telemetry
write path is deep in the LLM layer and knows nothing about sessions). To
reconstruct a whole session's trace we therefore need to know which interaction
ids belonged to it. This tiny store records that mapping as each turn runs, so
:func:`src.observability.trace.assemble_trace` can join a session's model runs
even when no per-turn evidence carried the interaction id.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.memory.db import get_connection
from src.memory.schema import init_all


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_link(
    session_id: str,
    interaction_id: str,
    *,
    user_id: str | None = None,
    turn_index: int | None = None,
) -> None:
    """Record that ``interaction_id`` ran under ``session_id`` (idempotent)."""
    if not session_id or not interaction_id:
        return
    init_all()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO session_interactions
                (session_id, user_id, interaction_id, turn_index, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, interaction_id, turn_index, _now()),
        )


def interaction_ids_for_user(user_id: str) -> list[str]:
    """Return every interaction id recorded for a user, across all sessions.

    ``model_runs`` carries no ``user_id`` column (see module docstring); this
    is the bridge a privacy export/deletion needs to find which model runs
    belong to a user, by way of the interaction ids their sessions recorded.
    """
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT interaction_id FROM session_interactions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [r["interaction_id"] for r in rows]


def delete_for_user(user_id: str) -> int:
    """Delete every session<->interaction link for ``user_id`` (Phase 21 deletion)."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM session_interactions WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def interactions_for_session(session_id: str, user_id: str | None = None) -> list[str]:
    """Return the interaction ids recorded for a session, oldest first.

    When ``user_id`` is given, only links recorded for that user are returned.
    Callers exposing this over an auth-scoped API (the trace route) MUST pass
    ``user_id`` — otherwise one user could reconstruct another user's LLM-call
    telemetry (provider/latency/tokens/cost) by supplying a known or guessed
    session id, since ``model_runs`` itself carries no user/session column and
    is joined in purely via this link table.
    """
    init_all()
    clauses = ["session_id = ?"]
    params: list[str] = [session_id]
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = " AND ".join(clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT interaction_id FROM session_interactions WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()
    return [r["interaction_id"] for r in rows]
