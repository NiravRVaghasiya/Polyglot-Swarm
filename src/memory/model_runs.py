"""Model-run store — durable sink for LLM call telemetry.

The LLM layer (:mod:`src.llm.telemetry`) records a :class:`ModelRun` for every
call in a bounded in-memory buffer and fans out to registered sinks. This
module is the durable sink: calling :func:`enable_persistence` registers a sink
that writes each run to the ``model_runs`` table, giving cost/latency/token
history that survives restarts (Phase 17/22 observability + cost tracking).

Persistence is opt-in so unit tests and offline runs don't spend I/O unless
they want it; the API enables it at startup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.memory.db import get_connection
from src.memory.schema import init_all

if TYPE_CHECKING:
    from src.llm.telemetry import ModelRun


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_run(run: ModelRun) -> int:
    """Persist one model run. Returns the new row id."""
    init_all()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO model_runs (provider, tier, model, operation, latency_ms,
                                    input_tokens, output_tokens, cost_usd, success,
                                    error, interaction_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.provider,
                run.tier,
                run.model,
                run.operation,
                run.latency_ms,
                run.input_tokens,
                run.output_tokens,
                run.cost_usd,
                1 if run.success else 0,
                run.error,
                run.interaction_id,
                run.timestamp or _now(),
            ),
        )
        row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def _sink(run: ModelRun) -> None:
    """Telemetry sink adapter: persist the run, discarding the row id."""
    record_run(run)


def enable_persistence() -> None:
    """Register the durable model-runs sink with the telemetry module."""
    from src.llm import telemetry

    telemetry.register_sink(_sink)


def get_runs(*, limit: int = 100) -> list[dict[str, Any]]:
    """Return recent persisted model runs, most recent first."""
    init_all()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM model_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_runs_by_interaction_ids(interaction_ids: list[str]) -> list[dict[str, Any]]:
    """Return model runs whose ``interaction_id`` is in ``interaction_ids``.

    ``model_runs`` has no ``user_id`` column, so this is how a privacy export
    finds "this user's" runs — via the interaction ids their sessions
    recorded (see :func:`src.observability.links.interaction_ids_for_user`).
    Returns an empty list without querying when ``interaction_ids`` is empty.
    """
    if not interaction_ids:
        return []
    init_all()
    placeholders = ",".join("?" * len(interaction_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM model_runs WHERE interaction_id IN ({placeholders})",
            interaction_ids,
        ).fetchall()
    return [dict(r) for r in rows]


def delete_by_interaction_ids(interaction_ids: list[str]) -> int:
    """Delete model runs whose ``interaction_id`` is in ``interaction_ids``.

    A no-op returning 0 when ``interaction_ids`` is empty.
    """
    if not interaction_ids:
        return 0
    init_all()
    placeholders = ",".join("?" * len(interaction_ids))
    with get_connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM model_runs WHERE interaction_id IN ({placeholders})",
            interaction_ids,
        )
        return cursor.rowcount


def cost_summary() -> dict[str, Any]:
    """Aggregate persisted runs: total calls, tokens, and cost."""
    init_all()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens,
                   COALESCE(SUM(cost_usd), 0) AS cost_usd,
                   COALESCE(AVG(latency_ms), 0) AS mean_latency_ms
            FROM model_runs
            """
        ).fetchone()
    return dict(row)
