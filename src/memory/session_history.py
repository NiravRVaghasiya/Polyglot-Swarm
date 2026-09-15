"""Session history store — durable log of conversation turns.

While LangGraph's checkpointer persists the *graph state* for resuming a
session, this store keeps a plain, queryable record of every user/assistant
turn for analytics, review, and building the conversation vector memory. Rows
are keyed by ``session_id`` and carry the ``user_id`` and ``language`` so they
can be aggregated per learner.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    language    TEXT NOT NULL,
    turn_index  INTEGER NOT NULL,
    role        TEXT NOT NULL,          -- "user" or "assistant"
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_turns_user ON conversation_turns(user_id, language);
"""


def init_db() -> None:
    """Create the conversation_turns table if it does not exist."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_turn(
    session_id: str,
    user_id: str,
    language: str,
    *,
    role: str,
    content: str,
    turn_index: int | None = None,
) -> int:
    """Append a single conversation turn. Returns the new row id.

    If ``turn_index`` is omitted it is auto-assigned as the next index for the
    session, so callers can simply append.
    """
    init_db()
    with get_connection() as conn:
        if turn_index is None:
            row = conn.execute(
                "SELECT COALESCE(MAX(turn_index), -1) + 1 AS next FROM "
                "conversation_turns WHERE session_id=?",
                (session_id,),
            ).fetchone()
            turn_index = int(row["next"])

        cursor = conn.execute(
            """
            INSERT INTO conversation_turns (
                session_id, user_id, language, turn_index, role, content, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, language, turn_index, role, content, _now()),
        )
        row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def record_turns(
    session_id: str,
    user_id: str,
    language: str,
    messages: list[dict[str, str]],
) -> int:
    """Append a batch of ``{"role", "content"}`` messages. Returns count added."""
    added = 0
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if not role or not content:
            continue
        record_turn(session_id, user_id, language, role=role, content=content)
        added += 1
    return added


def get_turns(session_id: str) -> list[dict[str, Any]]:
    """Return all turns for a session in order."""
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM conversation_turns WHERE session_id=? ORDER BY turn_index",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_turns_for_user(
    user_id: str,
    language: str | None = None,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return a user's most recent turns across sessions (newest first)."""
    init_db()
    with get_connection() as conn:
        if language is None:
            rows = conn.execute(
                "SELECT * FROM conversation_turns WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversation_turns WHERE user_id=? AND language=? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, language, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_for_user(user_id: str) -> int:
    """Delete every conversation-turn row for ``user_id`` (Phase 21 deletion)."""
    init_db()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM conversation_turns WHERE user_id=?", (user_id,))
        return cursor.rowcount
