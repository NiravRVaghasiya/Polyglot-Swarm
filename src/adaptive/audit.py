"""Audit trail of adaptive decisions (ADR-0033, migration 0008).

Every plan or learning path served through the API is appended to
``adaptive_decisions``, with:

- its engine version;
- the digest of the snapshot it was computed from;
- the full payload, including every rationale, component score and evidence
  id.

Rows are never updated. The latest path is also the "previous path" that the
next path's change list is explained against.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def record_decision(
    user_id: str,
    language: str,
    *,
    kind: str,
    engine: str,
    input_digest: str,
    payload: dict[str, Any],
) -> int:
    """Append one decision; returns its row id."""
    init_all()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO adaptive_decisions (user_id, language, kind, engine, input_digest, "
            "payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                language,
                kind,
                engine,
                input_digest,
                json.dumps(payload, sort_keys=True, default=str),
                datetime.now(UTC).isoformat(),
            ),
        )
        return int(cur.lastrowid or 0)


def _row(row: Any) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = json.loads(data["payload"])
    return data


def last_decision(user_id: str, language: str, *, kind: str) -> dict[str, Any] | None:
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM adaptive_decisions WHERE user_id=? AND language=? AND kind=? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, language, kind),
        ).fetchone()
    return _row(row) if row else None


def list_decisions(
    user_id: str, language: str, *, kind: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    init_all()
    query = "SELECT * FROM adaptive_decisions WHERE user_id=? AND language=?"
    params: list[Any] = [user_id, language]
    if kind is not None:
        query += " AND kind=?"
        params.append(kind)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_connection() as conn:
        return [_row(r) for r in conn.execute(query, params).fetchall()]


def all_for_user(user_id: str) -> list[dict[str, Any]]:
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM adaptive_decisions WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()
    return [_row(r) for r in rows]


def delete_for_user(user_id: str) -> int:
    init_all()
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM adaptive_decisions WHERE user_id=?", (user_id,))
        return int(cur.rowcount or 0)
