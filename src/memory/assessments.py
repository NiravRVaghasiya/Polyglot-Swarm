"""Assessment store — CEFR / skill assessments with confidence + sample size.

The plan treats CEFR as a multidimensional profile with confidence, not a
single validated number. This store records each assessment (overall or
per-skill) so progress can be shown as "B1- ± 0.3, 184 observations, medium
confidence" and later validated against expert ratings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_assessment(
    user_id: str,
    language: str,
    *,
    skill: str | None = None,
    cefr: str | None = None,
    score: float | None = None,
    confidence: float = 0.0,
    sample_size: int = 0,
    method: str | None = None,
    created_at: str | None = None,
) -> int:
    """Persist one assessment. Returns the new row id."""
    init_all()
    when = created_at or _now()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO assessments (user_id, language, skill, cefr, score,
                                     confidence, sample_size, method, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, language, skill, cefr, score, confidence, sample_size, method, when),
        )
        row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def latest_assessment(
    user_id: str, language: str, *, skill: str | None = None
) -> dict[str, Any] | None:
    """Return the most recent assessment for a user/language (optionally skill)."""
    init_all()
    with get_connection() as conn:
        if skill is None:
            row = conn.execute(
                "SELECT * FROM assessments WHERE user_id=? AND language=? AND skill IS NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (user_id, language),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM assessments WHERE user_id=? AND language=? AND skill=? "
                "ORDER BY created_at DESC LIMIT 1",
                (user_id, language, skill),
            ).fetchone()
    return dict(row) if row else None


def assessment_history(user_id: str, language: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return a user's assessment history, most recent first."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM assessments WHERE user_id=? AND language=? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, language, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def all_assessments_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return every assessment row for a user, across all languages."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM assessments WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_for_user(user_id: str) -> int:
    """Delete every assessment row for ``user_id`` (Phase 21 data deletion)."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM assessments WHERE user_id=?", (user_id,))
        return cursor.rowcount
