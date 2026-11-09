"""Processing-run and mastery-update history for the learner model (ADR-0031).

Append-only. Each time the knowledge model recomputes a learner's estimates
and something changed, it writes one ``lkm_processing_runs`` row (which
evidence it saw, as a digest plus high-water marks that let the exact evidence
set be reconstructed later) and one ``mastery_updates`` row per skill whose
estimate changed (before/after values and the evidence added or removed since
the previous run). Recomputing over unchanged evidence writes nothing, which is
what makes processing idempotent.
"""

from __future__ import annotations

import json
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all
from src.util import utc_now_iso as _now


def latest_run(user_id: str, language: str) -> dict[str, Any] | None:
    """Return the most recent processing run for a learner/language, or ``None``."""
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM lkm_processing_runs WHERE user_id=? AND language=? "
            "ORDER BY id DESC LIMIT 1",
            (user_id, language),
        ).fetchone()
    return dict(row) if row else None


def get_run(run_id: int) -> dict[str, Any] | None:
    """Return one processing run by id."""
    init_all()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM lkm_processing_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(user_id: str, language: str) -> list[dict[str, Any]]:
    """Return every processing run for a learner/language, oldest first."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM lkm_processing_runs WHERE user_id=? AND language=? ORDER BY id",
            (user_id, language),
        ).fetchall()
    return [dict(r) for r in rows]


def record_run(
    user_id: str,
    language: str,
    *,
    method: str,
    trigger: str,
    evidence_digest: str,
    evidence_count: int,
    evidence_high_water: int,
    supersession_high_water: int,
    updates: list[dict[str, Any]],
) -> int:
    """Write one run and its per-skill updates atomically. Returns the run id."""
    init_all()
    created = _now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO lkm_processing_runs (user_id, language, method, trigger,
                evidence_digest, evidence_count, evidence_high_water,
                supersession_high_water, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                language,
                method,
                trigger,
                evidence_digest,
                evidence_count,
                evidence_high_water,
                supersession_high_water,
                created,
            ),
        )
        run_id = cursor.lastrowid
        assert run_id is not None
        for u in updates:
            conn.execute(
                """
                INSERT INTO mastery_updates (run_id, user_id, language, skill, method,
                    evidence_digest, mastery_before, mastery_after, uncertainty_after,
                    status_before, status_after, baseline_mastery, independent_n,
                    new_event_ids, removed_event_ids, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    user_id,
                    language,
                    u["skill"],
                    method,
                    u["evidence_digest"],
                    u.get("mastery_before"),
                    u.get("mastery_after"),
                    u.get("uncertainty_after"),
                    u.get("status_before"),
                    u.get("status_after"),
                    u.get("baseline_mastery"),
                    u.get("independent_n"),
                    json.dumps(u.get("new_event_ids", [])),
                    json.dumps(u.get("removed_event_ids", [])),
                    created,
                ),
            )
    return run_id


def get_updates(user_id: str, language: str, *, skill: str | None = None) -> list[dict[str, Any]]:
    """Return mastery-update history, oldest first (optionally for one skill)."""
    init_all()
    params: list[Any] = [user_id, language]
    clause = ""
    if skill is not None:
        clause = " AND skill=?"
        params.append(skill)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM mastery_updates WHERE user_id=? AND language=?{clause} ORDER BY id",  # noqa: S608
            params,
        ).fetchall()
    out = []
    for r in rows:
        data = dict(r)
        data["new_event_ids"] = json.loads(data["new_event_ids"])
        data["removed_event_ids"] = json.loads(data["removed_event_ids"])
        out.append(data)
    return out


def delete_for_user(user_id: str) -> int:
    """Delete a user's LKM history (Phase 21 data deletion). Returns rows removed."""
    init_all()
    with get_connection() as conn:
        a = conn.execute("DELETE FROM mastery_updates WHERE user_id=?", (user_id,)).rowcount
        b = conn.execute("DELETE FROM lkm_processing_runs WHERE user_id=?", (user_id,)).rowcount
    return int(a) + int(b)
