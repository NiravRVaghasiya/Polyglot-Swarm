"""Per-skill competence store (the learner model's belief layer).

Represents skill-specific mastery (speaking, listening, reading, writing,
grammar, vocabulary, pragmatics, ...) with an uncertainty and a sample size,
rather than collapsing competence into a single number. The full mastery
*engine* (Bayesian/IRT/weighted-evidence) is Phase 6; this store is the durable
interface it will read and write, available now so evidence and assessments
have somewhere to land.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all

# The canonical skill dimensions (kept open — callers may use others).
SKILLS = (
    "speaking",
    "listening",
    "reading",
    "writing",
    "grammar",
    "vocabulary",
    "pragmatics",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def upsert_skill(
    user_id: str,
    language: str,
    skill: str,
    *,
    mastery: float,
    uncertainty: float = 0.5,
    sample_size: int = 0,
) -> dict[str, Any]:
    """Insert or replace a skill's current belief. Returns the resulting row."""
    init_all()
    mastery = max(0.0, min(1.0, mastery))
    uncertainty = max(0.0, min(1.0, uncertainty))
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO skill_states (user_id, language, skill, mastery, uncertainty,
                                      sample_size, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, language, skill) DO UPDATE SET
                mastery = excluded.mastery,
                uncertainty = excluded.uncertainty,
                sample_size = excluded.sample_size,
                updated_at = excluded.updated_at
            """,
            (user_id, language, skill, mastery, uncertainty, sample_size, _now()),
        )
        row = conn.execute(
            "SELECT * FROM skill_states WHERE user_id=? AND language=? AND skill=?",
            (user_id, language, skill),
        ).fetchone()
    return dict(row)


def get_skills(user_id: str, language: str) -> dict[str, dict[str, Any]]:
    """Return all skill beliefs for a user/language, keyed by skill name."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM skill_states WHERE user_id=? AND language=?",
            (user_id, language),
        ).fetchall()
    return {r["skill"]: dict(r) for r in rows}


def upsert_estimate(
    user_id: str,
    language: str,
    skill: str,
    *,
    mastery: float,
    uncertainty: float,
    sample_size: int,
    method: str,
    status: str,
    mastery_low: float | None,
    mastery_high: float | None,
    evidence_index: float,
    independent_n: float,
    effective_n: float,
    evidence_quality: float,
    baseline_mastery: float | None,
    coverage: dict[str, Any],
    last_evidence_at: str | None,
    evidence_digest: str,
) -> None:
    """Materialize an evidence-derived (ADR-0031) estimate into ``skill_states``.

    The row is a cache of a deterministic projection of the evidence store; the
    knowledge model rewrites it whenever the projection changes.
    """
    import json

    init_all()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO skill_states (user_id, language, skill, mastery, uncertainty,
                sample_size, updated_at, method, status, mastery_low, mastery_high,
                evidence_index, independent_n, effective_n, evidence_quality,
                baseline_mastery, coverage, last_evidence_at, evidence_digest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, language, skill) DO UPDATE SET
                mastery = excluded.mastery,
                uncertainty = excluded.uncertainty,
                sample_size = excluded.sample_size,
                updated_at = excluded.updated_at,
                method = excluded.method,
                status = excluded.status,
                mastery_low = excluded.mastery_low,
                mastery_high = excluded.mastery_high,
                evidence_index = excluded.evidence_index,
                independent_n = excluded.independent_n,
                effective_n = excluded.effective_n,
                evidence_quality = excluded.evidence_quality,
                baseline_mastery = excluded.baseline_mastery,
                coverage = excluded.coverage,
                last_evidence_at = excluded.last_evidence_at,
                evidence_digest = excluded.evidence_digest
            """,
            (
                user_id,
                language,
                skill,
                max(0.0, min(1.0, mastery)),
                max(0.0, min(1.0, uncertainty)),
                sample_size,
                _now(),
                method,
                status,
                mastery_low,
                mastery_high,
                evidence_index,
                independent_n,
                effective_n,
                evidence_quality,
                baseline_mastery,
                json.dumps(coverage, sort_keys=True),
                last_evidence_at,
                evidence_digest,
            ),
        )


def delete_skill(user_id: str, language: str, skill: str) -> None:
    """Remove one materialized skill row (its evidence was retracted)."""
    init_all()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM skill_states WHERE user_id=? AND language=? AND skill=?",
            (user_id, language, skill),
        )


def get_all_skills_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return every skill-belief row for a user, across all languages."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM skill_states WHERE user_id=?",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_for_user(user_id: str) -> int:
    """Delete every skill-belief row for ``user_id`` (Phase 21 data deletion)."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM skill_states WHERE user_id=?", (user_id,))
        return cursor.rowcount
