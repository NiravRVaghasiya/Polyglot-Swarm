"""Persistence for evidence events (the ``evidence`` table).

Events are append-only: once written they are never mutated, which is what
makes them a trustworthy audit trail for how the learner model reached its
current beliefs. ``event_id`` is unique, so re-inserting the same event is a
no-op (idempotent replay).

Corrections never edit a row. :func:`supersede_event` appends a row to
``evidence_supersessions`` (and optionally a replacement event whose
``supersedes`` field names the original); :func:`active_events` then returns the
evidence set with superseded rows left out, in a stable order, which is what
the learner model replays (ADR-0031).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.evidence.events import DifficultyBasis, LearningEvent, evidence_fingerprint
from src.memory.db import get_connection
from src.memory.schema import init_all

#: Columns written for every event, in insert order.
_COLUMNS = (
    "event_id",
    "user_id",
    "language",
    "session_id",
    "interaction_id",
    "event_type",
    "skill",
    "subskill",
    "objective_id",
    "item_id",
    "observed",
    "expected",
    "assessment",
    "confidence",
    "task_type",
    "difficulty",
    "difficulty_basis",
    "source",
    "model_version",
    "rubric_version",
    "prompt_version",
    "correlation_id",
    "supersedes",
    "fingerprint",
    "schema_version",
    "payload",
    "created_at",
    "recorded_at",
    "modality",
    "media_ref",
    "processing",
    "transcription_confidence",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_event(event: LearningEvent) -> None:
    """Persist a single evidence event (idempotent on ``event_id``)."""
    record_events([event])


def record_events(events: list[LearningEvent]) -> int:
    """Persist a batch of events. Returns the number newly inserted.

    An event whose ``supersedes`` names an earlier event also records that
    supersession, so a correction is one call.
    """
    if not events:
        return 0
    init_all()
    inserted = 0
    recorded_at = _now()
    placeholders = ", ".join("?" for _ in _COLUMNS)
    with get_connection() as conn:
        for e in events:
            values = {
                "event_id": e.event_id,
                "user_id": e.user_id,
                "language": e.language,
                "session_id": e.session_id,
                "interaction_id": e.interaction_id,
                "event_type": e.event_type.value,
                "skill": e.skill,
                "subskill": e.subskill,
                "objective_id": e.objective_id,
                "item_id": e.item_id,
                "observed": e.observed,
                "expected": e.expected,
                "assessment": e.assessment,
                "confidence": e.confidence,
                "task_type": e.task_type,
                "difficulty": e.difficulty,
                "difficulty_basis": e.difficulty_basis.value,
                "source": e.source,
                "model_version": e.model_version,
                "rubric_version": e.rubric_version,
                "prompt_version": e.prompt_version,
                "correlation_id": e.correlation_id,
                "supersedes": e.supersedes,
                "fingerprint": e.fingerprint(),
                "schema_version": e.schema_version,
                "payload": json.dumps(e.payload),
                "created_at": e.created_at,
                "recorded_at": recorded_at,
                "modality": e.modality,
                "media_ref": None if e.media_ref is None else json.dumps(e.media_ref),
                "processing": None if e.processing is None else json.dumps(e.processing),
                "transcription_confidence": e.transcription_confidence,
            }
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO evidence ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
                tuple(values[c] for c in _COLUMNS),
            )
            inserted += cursor.rowcount
            if cursor.rowcount and e.supersedes:
                _insert_supersession(
                    conn,
                    e.user_id,
                    e.supersedes,
                    e.event_id,
                    str(e.payload.get("correction_reason", "")),
                )
    return inserted


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("payload"), str):
        data["payload"] = json.loads(data["payload"])
    for key in ("media_ref", "processing"):
        if isinstance(data.get(key), str):
            data[key] = json.loads(data[key])
    if not data.get("modality"):
        data["modality"] = "text"
    # Legacy (schema v1) rows predate these columns' defaults being meaningful.
    if not data.get("difficulty_basis"):
        data["difficulty_basis"] = DifficultyBasis.UNKNOWN.value
    if not data.get("fingerprint"):
        data["fingerprint"] = evidence_fingerprint(data)
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


def get_event(event_id: str) -> dict[str, Any] | None:
    """Return one stored event by id, or ``None``."""
    init_all()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM evidence WHERE event_id=?", (event_id,)).fetchone()
    return _row_to_dict(row) if row else None


def active_events(
    user_id: str,
    language: str,
    *,
    evidence_high_water: int | None = None,
    supersession_high_water: int | None = None,
) -> list[dict[str, Any]]:
    """Return the learner's non-superseded evidence in a stable replay order.

    Ordered by observation time, then ``event_id`` as a tie-breaker, never by
    insertion order, so the same evidence imported in a different order
    replays identically. The high-water marks (``evidence.id`` /
    ``evidence_supersessions.id``) reconstruct the active set as it was at an
    earlier processing run.
    """
    init_all()
    params: list[Any] = [user_id, language]
    ev_clause = ""
    if evidence_high_water is not None:
        ev_clause = " AND e.id <= ?"
        params.append(evidence_high_water)
    sup_clause = ""
    sup_params: list[Any] = [user_id]
    if supersession_high_water is not None:
        sup_clause = " AND s.id <= ?"
        sup_params.append(supersession_high_water)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT e.* FROM evidence e
            WHERE e.user_id = ? AND e.language = ?{ev_clause}
              AND e.event_id NOT IN (
                  SELECT s.superseded_event_id FROM evidence_supersessions s
                  WHERE s.user_id = ?{sup_clause}
              )
            ORDER BY e.created_at, e.event_id
            """,
            (*params, *sup_params),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def high_water_marks(user_id: str) -> tuple[int, int]:
    """Return ``(max evidence.id, max evidence_supersessions.id)`` for a user (0 if none)."""
    init_all()
    with get_connection() as conn:
        ev = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS n FROM evidence WHERE user_id=?", (user_id,)
        ).fetchone()
        sup = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS n FROM evidence_supersessions WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return int(ev["n"]), int(sup["n"])


def _insert_supersession(
    conn: Any,
    user_id: str,
    superseded_event_id: str,
    superseding_event_id: str | None,
    reason: str,
) -> bool:
    # ``IS`` (not ``=``) so a NULL replacement (a retraction) matches too:
    # SQLite's UNIQUE treats NULLs as distinct, so it cannot enforce this alone.
    exists = conn.execute(
        "SELECT 1 FROM evidence_supersessions WHERE superseded_event_id = ? "
        "AND superseding_event_id IS ?",
        (superseded_event_id, superseding_event_id),
    ).fetchone()
    if exists:
        return False
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO evidence_supersessions
            (user_id, superseded_event_id, superseding_event_id, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, superseded_event_id, superseding_event_id, reason, _now()),
    )
    return bool(cursor.rowcount)


def supersede_event(
    event_id: str,
    *,
    replacement: LearningEvent | None = None,
    reason: str = "",
) -> bool:
    """Mark ``event_id`` as superseded, optionally by a ``replacement`` event.

    The original row is kept unchanged (it stays in the audit trail and in
    :func:`get_events`) but is left out of :func:`active_events`. With a
    ``replacement`` this is a correction (the replacement's ``supersedes`` is
    set to ``event_id``); without one it is a retraction. Idempotent: repeating
    the same supersession is a no-op and returns ``False``.

    Raises:
        KeyError: ``event_id`` is not a stored event.
        ValueError: the replacement belongs to a different learner.
    """
    original = get_event(event_id)
    if original is None:
        raise KeyError(f"unknown evidence event {event_id!r}")
    user_id = str(original["user_id"])
    if replacement is not None:
        if replacement.user_id != user_id:
            raise ValueError("a replacement event must belong to the same learner")
        replacement = replacement.model_copy(
            update={
                "supersedes": event_id,
                "payload": {**replacement.payload, "correction_reason": reason},
            }
        )
        before = _supersession_count(user_id)
        record_events([replacement])
        return _supersession_count(user_id) > before
    init_all()
    with get_connection() as conn:
        return _insert_supersession(conn, user_id, event_id, None, reason)


def _supersession_count(user_id: str) -> int:
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM evidence_supersessions WHERE user_id=?", (user_id,)
        ).fetchone()
    return int(row["n"])


def get_supersessions(user_id: str) -> list[dict[str, Any]]:
    """Return every supersession recorded for a user, oldest first."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM evidence_supersessions WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


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
    Supersession records for the user go with it.
    """
    init_all()
    with get_connection() as conn:
        conn.execute("DELETE FROM evidence_supersessions WHERE user_id=?", (user_id,))
        cursor = conn.execute("DELETE FROM evidence WHERE user_id=?", (user_id,))
        return cursor.rowcount
