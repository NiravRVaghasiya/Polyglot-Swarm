"""Append-only audit log for security-relevant events.

The ``audit_log`` table (migration 0006) is never updated or deleted from by
this module — only inserted into and read — so it stays a trustworthy record
of what happened (logins, registrations, data export/deletion, backups, ...).
Deliberately generic: one table with an ``event_type`` and a JSON ``detail``
blob, rather than a table per event kind, since the set of auditable events
is expected to grow as the product does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def _now() -> str:
    return datetime.now(UTC).isoformat()


def log_event(
    event_type: str, *, user_id: str | None = None, detail: dict[str, Any] | None = None
) -> int:
    """Append one audit-log entry. Returns the new row id.

    Never raises on a malformed ``detail`` (falls back to ``{}`` if it
    doesn't serialize) — an audit-logging failure must not itself break the
    operation being audited.
    """
    init_all()
    try:
        detail_json = json.dumps(detail or {})
    except (TypeError, ValueError):
        detail_json = "{}"
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO audit_log (event_type, user_id, detail, created_at) VALUES (?, ?, ?, ?)",
            (event_type, user_id, detail_json, _now()),
        )
        row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("detail"), str):
        try:
            data["detail"] = json.loads(data["detail"])
        except json.JSONDecodeError:
            data["detail"] = {}
    return data


def recent_events(
    *,
    user_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return audit-log entries, most recent first, with optional filters."""
    init_all()
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def anonymize_for_user(user_id: str) -> int:
    """Detach ``user_id`` from a deleted account's audit-log entries.

    The audit log is append-only by design (a trustworthy security record),
    so a right-to-erasure request is honored by *anonymizing* — nulling the
    ``user_id`` column while keeping ``event_type``/``detail``/timestamp
    intact — rather than deleting rows outright, preserving the log's value
    for security forensics without retaining personal linkage. Returns the
    number of rows updated.
    """
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("UPDATE audit_log SET user_id = NULL WHERE user_id = ?", (user_id,))
        return cursor.rowcount
