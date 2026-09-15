"""Experiment store — controlled comparisons, variant assignment, and outcomes.

Supports the learning-science experiment platform (Phase 19):

- define an experiment with named variants (:func:`create_experiment`),
- assign each user to a variant deterministically, stable across sessions
  (:func:`assign`/:func:`get_assignment`),
- record measured outcomes at each point in the study — pre-test,
  intervention, immediate post-test, and 1/7/30-day delayed tests
  (:func:`record_outcome`/:func:`get_outcomes`/:func:`summarize_outcomes`).

An outcome's ``value`` is deliberately a single float (e.g. a CEFR-band
ordinal, a mastery score, a recall-accuracy percentage) rather than an
open-ended blob, so aggregation across users/variants is simple; richer detail
can still ride along in ``payload``. Callers typically compute that value from
the existing learner model (e.g. :func:`src.assessment.cefr_profile.
build_cefr_profile`) rather than this module reimplementing measurement.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_experiment(
    name: str,
    variants: list[str],
    *,
    description: str = "",
    status: str = "active",
) -> dict[str, Any]:
    """Create (or update) an experiment definition. Returns the row."""
    init_all()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO experiments (name, description, variants, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                variants = excluded.variants,
                status = excluded.status
            """,
            (name, description, json.dumps(variants), status, _now()),
        )
        row = conn.execute("SELECT * FROM experiments WHERE name=?", (name,)).fetchone()
    data = dict(row)
    data["variants"] = json.loads(data["variants"])
    return data


def _stable_variant(experiment: str, user_id: str, variants: list[str]) -> str:
    """Deterministically pick a variant for a user (stable across sessions)."""
    digest = hashlib.sha256(f"{experiment}:{user_id}".encode()).hexdigest()
    return variants[int(digest, 16) % len(variants)]


def assign(experiment: str, user_id: str) -> str:
    """Return the user's variant for an experiment, assigning one if needed."""
    init_all()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT variant FROM experiment_assignments WHERE experiment=? AND user_id=?",
            (experiment, user_id),
        ).fetchone()
        if existing is not None:
            return str(existing["variant"])

        exp = conn.execute(
            "SELECT variants FROM experiments WHERE name=?", (experiment,)
        ).fetchone()
        if exp is None:
            raise ValueError(f"unknown experiment: {experiment!r}")
        variants = json.loads(exp["variants"])
        if not variants:
            raise ValueError(f"experiment {experiment!r} has no variants")

        variant = _stable_variant(experiment, user_id, variants)
        conn.execute(
            """
            INSERT INTO experiment_assignments (experiment, user_id, variant, assigned_at)
            VALUES (?, ?, ?, ?)
            """,
            (experiment, user_id, variant, _now()),
        )
    return variant


def assign_to_variant(experiment: str, user_id: str, variant: str) -> str:
    """Assign a user to a SPECIFIC variant (idempotent on the existing one).

    Unlike :func:`assign`, which picks a variant by a stable hash, this forces
    a chosen variant — used by the ablation runner, which deliberately places
    each synthetic learner in a named arm rather than randomizing. If the user
    already has an assignment for this experiment it is returned unchanged (a
    user's variant must be stable across a study), so this never silently
    reassigns someone mid-experiment.
    """
    init_all()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT variant FROM experiment_assignments WHERE experiment=? AND user_id=?",
            (experiment, user_id),
        ).fetchone()
        if existing is not None:
            return str(existing["variant"])
        conn.execute(
            """
            INSERT INTO experiment_assignments (experiment, user_id, variant, assigned_at)
            VALUES (?, ?, ?, ?)
            """,
            (experiment, user_id, variant, _now()),
        )
    return variant


def get_assignment(experiment: str, user_id: str) -> str | None:
    """Return a user's assigned variant, or ``None`` if unassigned."""
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT variant FROM experiment_assignments WHERE experiment=? AND user_id=?",
            (experiment, user_id),
        ).fetchone()
    return str(row["variant"]) if row else None


# --------------------------------------------------------------------------- #
# Outcomes — measurements at each point in a controlled comparison (Phase 19).
# --------------------------------------------------------------------------- #

#: The measurement points the plan's pre/post/delayed-test design calls for.
#: Not enforced as a DB constraint (kept as plain TEXT for forward
#: compatibility with new points), but this is the vocabulary callers should use.
MEASUREMENT_POINTS = (
    "pre_test",
    "intervention",
    "immediate_post",
    "delayed_1d",
    "delayed_7d",
    "delayed_30d",
)


def record_outcome(
    experiment: str,
    user_id: str,
    measurement_point: str,
    metric: str,
    value: float,
    *,
    variant: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Record one measured outcome for a user's experiment assignment.

    ``variant`` defaults to the user's current assignment (via
    :func:`get_assignment`) when not supplied, so callers measuring an
    already-assigned user don't need to look it up separately. Raises
    :class:`ValueError` if no variant is supplied and none can be resolved
    (the user was never assigned) — an outcome with no variant would be
    unanalyzable.

    Returns the new row id.
    """
    init_all()
    resolved_variant = variant or get_assignment(experiment, user_id)
    if resolved_variant is None:
        raise ValueError(
            f"cannot record outcome: user {user_id!r} has no variant assignment "
            f"for experiment {experiment!r} (assign one first, or pass variant=)"
        )
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO outcomes
                (experiment, user_id, variant, measurement_point, metric, value,
                 payload, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment,
                user_id,
                resolved_variant,
                measurement_point,
                metric,
                value,
                json.dumps(payload or {}),
                _now(),
            ),
        )
        row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def _outcome_row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("payload"), str):
        data["payload"] = json.loads(data["payload"])
    return data


def get_outcomes(
    experiment: str,
    *,
    user_id: str | None = None,
    measurement_point: str | None = None,
) -> list[dict[str, Any]]:
    """Return recorded outcomes for an experiment, optionally filtered.

    Ordered oldest first, which keeps a single user's measurement points in
    study order (pre-test before post-test, etc.) as long as they were
    recorded in that order.
    """
    init_all()
    clauses = ["experiment = ?"]
    params: list[Any] = [experiment]
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if measurement_point is not None:
        clauses.append("measurement_point = ?")
        params.append(measurement_point)
    where = " AND ".join(clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM outcomes WHERE {where} ORDER BY id ASC", params
        ).fetchall()
    return [_outcome_row_to_dict(r) for r in rows]


def all_assignments_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return every experiment assignment for a user, across all experiments."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM experiment_assignments WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def all_outcomes_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return every outcome for a user, across all experiments."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM outcomes WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
    return [_outcome_row_to_dict(r) for r in rows]


def delete_for_user(user_id: str) -> dict[str, int]:
    """Delete every experiment assignment and outcome for ``user_id``.

    Phase 21 data deletion. The ``experiments`` definitions themselves (shared
    across users) are untouched — only this user's participation records.
    """
    init_all()
    with get_connection() as conn:
        assignments = conn.execute(
            "DELETE FROM experiment_assignments WHERE user_id = ?", (user_id,)
        ).rowcount
        outcomes = conn.execute("DELETE FROM outcomes WHERE user_id = ?", (user_id,)).rowcount
    return {"experiment_assignments": assignments, "outcomes": outcomes}


# --------------------------------------------------------------------------- #
# Delayed-retention scheduling — the producer that makes 1d/7d/30d real.
# --------------------------------------------------------------------------- #

#: How long after a user's assignment each delayed measurement becomes due,
#: in seconds. This is what turns the delayed_* measurement points from a
#: vocabulary of strings into an actual schedule: a background job (or the
#: `polyglot experiment due` command) asks `due_measurements` which users are
#: past each offset and still un-measured at that point, and measures them.
_DELAY_OFFSET_SECONDS: dict[str, float] = {
    "delayed_1d": 1 * 24 * 3600,
    "delayed_7d": 7 * 24 * 3600,
    "delayed_30d": 30 * 24 * 3600,
}


def _parse_ts(value: str) -> datetime:
    """Parse an ISO timestamp stored by this module back into a datetime."""
    return datetime.fromisoformat(value)


def due_measurements(
    experiment: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return the delayed measurements that are due but not yet recorded.

    For every assignment in ``experiment``, a delayed point (``delayed_1d`` /
    ``delayed_7d`` / ``delayed_30d``) is *due* once
    ``now >= assigned_at + offset`` and no outcome has been recorded for that
    (user, point) yet. This is the missing producer the audit called out: it
    converts the assignment timestamp plus a fixed offset into a concrete
    "measure this learner now" work list, so delayed retention can be measured
    by a scheduled job rather than only by hand.

    Args:
        experiment: The experiment name.
        now: Injectable clock for deterministic tests; defaults to UTC now.

    Returns:
        A list of ``{"user_id", "variant", "measurement_point", "due_at"}``
        dicts, one per due-but-unrecorded delayed measurement, oldest-due
        first. Empty when nothing is due.
    """
    init_all()
    current = now or datetime.now(UTC)
    with get_connection() as conn:
        assignments = conn.execute(
            "SELECT user_id, variant, assigned_at FROM experiment_assignments WHERE experiment = ?",
            (experiment,),
        ).fetchall()
        recorded = conn.execute(
            "SELECT DISTINCT user_id, measurement_point FROM outcomes WHERE experiment = ?",
            (experiment,),
        ).fetchall()

    already = {(r["user_id"], r["measurement_point"]) for r in recorded}
    due: list[dict[str, Any]] = []
    for assignment in assignments:
        assigned_at = _parse_ts(assignment["assigned_at"])
        for point, offset in _DELAY_OFFSET_SECONDS.items():
            due_at = assigned_at + timedelta(seconds=offset)
            if current >= due_at and (assignment["user_id"], point) not in already:
                due.append(
                    {
                        "user_id": assignment["user_id"],
                        "variant": assignment["variant"],
                        "measurement_point": point,
                        "due_at": due_at.isoformat(),
                    }
                )
    due.sort(key=lambda d: d["due_at"])
    return due


def summarize_outcomes(experiment: str, metric: str) -> dict[str, dict[str, Any]]:
    """Aggregate one metric by variant and measurement point: mean, n.

    Returns ``{variant: {measurement_point: {"mean": float, "n": int}}}`` — the
    minimal summary a controlled comparison needs to compare arms (e.g. does
    the treatment's ``immediate_post`` mean exceed control's for
    ``overall_cefr_ordinal``). Deliberately simple (no significance testing);
    richer analysis can be layered on `get_outcomes`'s raw rows.
    """
    rows = [r for r in get_outcomes(experiment) if r["metric"] == metric]
    summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        variant = row["variant"]
        point = row["measurement_point"]
        by_point = summary.setdefault(variant, {})
        bucket = by_point.setdefault(point, {"values": []})
        bucket["values"].append(row["value"])
    for by_point in summary.values():
        for bucket in by_point.values():
            values = bucket.pop("values")
            bucket["n"] = len(values)
            bucket["mean"] = sum(values) / len(values) if values else 0.0
    return summary
