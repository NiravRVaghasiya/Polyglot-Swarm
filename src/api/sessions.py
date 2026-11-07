"""Active chat sessions for the API: durable, capped and recoverable.

Holds each user's live :class:`LearnerState` between HTTP requests (keyed by
``(user_id, session_id)``) and runs one conversation turn at a time through
the compiled graph.

**Durability (ADR-0035, R1).** The in-memory dict is only a cache. After
every turn the state is snapshotted to ``active_sessions``, so:

- a restart or deploy loses nothing: :func:`get_session` rehydrates the
  session from its snapshot on the next request;
- an abandoned session (the learner closed the tab) is still finalized: the
  maintenance task (:func:`recover_idle_sessions`) finalizes sessions idle
  longer than ``settings.session_idle_finalize_hours``, so their evidence
  reaches the learner model.

**Finalized once.** :func:`finalize` claims a session (``active`` →
``finalizing``) with a conditional update before running end-of-session
work, so a double click, a client retry and the recovery task cannot
finalize the same session twice. If finalization fails, the claim is
released and recovery retries it later. The snapshot (which contains the
conversation) is cleared once the session is finalized; the durable turn log
lives in ``session_history``.

**Bounded (R7).** At most ``settings.max_active_sessions_per_user`` sessions
per user; starting another finalizes that user's least recently used one.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agents.adaptive import adaptive_node
from src.config import settings
from src.llm import governance
from src.observability import metrics
from src.observability.context import interaction_scope
from src.orchestrator.graph import compile_turn_graph
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.api.sessions")

# Compiled once and reused across requests. No checkpointer: this registry owns
# each session's state and resends it every turn (see compile_turn_graph).
_graph = compile_turn_graph()

# (user_id, session_id) -> LearnerState (a cache over ``active_sessions``)
_active: dict[tuple[str, str], LearnerState] = {}
_last_used: dict[tuple[str, str], float] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _conn() -> Any:
    from src.memory.db import get_connection

    return get_connection()


def active_count() -> int:
    """Sessions currently cached in this process (a metrics gauge)."""
    return len(_active)


# --- snapshots -----------------------------------------------------------------


def persist_snapshot(state: LearnerState) -> None:
    """Upsert the session's snapshot (called after start and every turn)."""
    now = _now()
    payload = json.dumps(state, default=str, ensure_ascii=False)
    with _conn() as conn:
        conn.execute(
            "INSERT INTO active_sessions "
            "(user_id, session_id, language, status, state_json, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?) "
            "ON CONFLICT(user_id, session_id) DO UPDATE SET state_json = excluded.state_json, "
            "updated_at = excluded.updated_at WHERE active_sessions.status = 'active'",
            (state["user_id"], state["session_id"], state["language"], payload, now, now),
        )


def _load_snapshot(user_id: str, session_id: str) -> LearnerState | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT state_json FROM active_sessions "
            "WHERE user_id = ? AND session_id = ? AND status = 'active'",
            (user_id, session_id),
        ).fetchone()
    if row is None or not row["state_json"]:
        return None
    state: LearnerState = json.loads(row["state_json"])
    return state


# --- registry ------------------------------------------------------------------


def register_session(user_id: str, state: LearnerState) -> None:
    key = (user_id, state["session_id"])
    _active[key] = state
    _last_used[key] = time.monotonic()
    persist_snapshot(state)
    metrics.SESSION_EVENTS.inc(event="started")


def get_session(user_id: str, session_id: str) -> LearnerState | None:
    """The live session, rehydrated from its snapshot after a restart."""
    key = (user_id, session_id)
    state = _active.get(key)
    if state is None:
        state = _load_snapshot(user_id, session_id)
        if state is None:
            return None
        _active[key] = state
        metrics.SESSION_EVENTS.inc(event="rehydrated")
    _last_used[key] = time.monotonic()
    return state


def drop_session(user_id: str, session_id: str) -> None:
    _active.pop((user_id, session_id), None)
    _last_used.pop((user_id, session_id), None)


def _active_ids(user_id: str) -> list[tuple[str, str]]:
    """``(session_id, updated_at)`` of the user's active sessions, oldest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT session_id, updated_at FROM active_sessions "
            "WHERE user_id = ? AND status = 'active' ORDER BY updated_at",
            (user_id,),
        ).fetchall()
    return [(r["session_id"], r["updated_at"]) for r in rows]


async def enforce_session_cap(user_id: str) -> None:
    """Finalize the user's oldest sessions until one more fits under the cap."""
    cap = settings.max_active_sessions_per_user
    if cap <= 0:
        return
    active = _active_ids(user_id)
    for session_id, _ in active[: max(0, len(active) - cap + 1)]:
        await finalize(user_id, session_id)
        metrics.SESSION_EVENTS.inc(event="evicted")


# --- finalization --------------------------------------------------------------


def _claim(user_id: str, session_id: str) -> bool:
    """``active`` → ``finalizing``; ``True`` if this caller won the claim.

    A session with no snapshot row (started before migration 0010) can be
    finalized by whoever holds it in memory.
    """
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE active_sessions SET status = 'finalizing', updated_at = ? "
            "WHERE user_id = ? AND session_id = ? AND status = 'active'",
            (_now(), user_id, session_id),
        )
        if cur.rowcount == 1:
            return True
        exists = conn.execute(
            "SELECT 1 FROM active_sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ).fetchone()
    return exists is None and (user_id, session_id) in _active


def _set_status(user_id: str, session_id: str, status: str, *, clear_state: bool) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE active_sessions SET status = ?, updated_at = ?"  # noqa: S608
            + (", state_json = NULL" if clear_state else "")
            + " WHERE user_id = ? AND session_id = ?",
            (status, _now(), user_id, session_id),
        )


async def finalize(
    user_id: str, session_id: str, *, state: LearnerState | None = None
) -> dict[str, Any] | None:
    """Finalize a session exactly once; ``None`` if it was not claimable.

    Runs :func:`src.orchestrator.lifecycle.finalize_session`, marks the
    session ``finalized`` and clears its snapshot. On failure the claim is
    released (status back to ``active``) and the error re-raised, so the
    recovery task retries it.
    """
    from src.orchestrator.lifecycle import finalize_session

    state = state or get_session(user_id, session_id)
    if state is None or not _claim(user_id, session_id):
        return None
    try:
        result = await finalize_session(state)
    except Exception:
        _set_status(user_id, session_id, "active", clear_state=False)
        metrics.SESSION_EVENTS.inc(event="finalize_failed")
        raise
    _set_status(user_id, session_id, "finalized", clear_state=True)
    drop_session(user_id, session_id)
    metrics.SESSION_EVENTS.inc(event="finalized")
    return result


async def recover_idle_sessions(*, idle_hours: float | None = None) -> dict[str, int]:
    """Finalize sessions idle longer than ``idle_hours``; release stuck claims.

    A claim stuck in ``finalizing`` for over an hour (the process died
    mid-finalization) is released and retried. A retry can duplicate part of
    the turn log or analytics, but not learner evidence: the learner model
    counts equal evidence fingerprints once.
    """
    idle_hours = settings.session_idle_finalize_hours if idle_hours is None else idle_hours
    now = datetime.now(UTC)
    idle_cutoff = (now - timedelta(hours=idle_hours)).isoformat()
    stuck_cutoff = (now - timedelta(hours=1)).isoformat()
    with _conn() as conn:
        released = conn.execute(
            "UPDATE active_sessions SET status = 'active' "
            "WHERE status = 'finalizing' AND updated_at < ?",
            (stuck_cutoff,),
        ).rowcount
        rows = conn.execute(
            "SELECT user_id, session_id FROM active_sessions "
            "WHERE status = 'active' AND updated_at < ? ORDER BY updated_at",
            (idle_cutoff,),
        ).fetchall()
    outcome = {"released": released, "finalized": 0, "failed": 0}
    for row in rows:
        try:
            if await finalize(row["user_id"], row["session_id"]) is not None:
                outcome["finalized"] += 1
                metrics.SESSION_EVENTS.inc(event="recovered")
        except Exception as exc:  # noqa: BLE001 - one bad session must not stop recovery
            outcome["failed"] += 1
            logger.error("recovery could not finalize session %s: %s", row["session_id"], exc)
    return outcome


# --- turns ---------------------------------------------------------------------


async def run_turn(state: LearnerState, user_input: str) -> str:
    """Run one conversation turn through the graph, mutating ``state`` in place.

    Streams graph node updates and stops once the conversation node has produced
    its reply, merging each node's partial update back into ``state``. Returns
    the assistant reply. The updated state is snapshotted before returning.
    """
    state["last_user_input"] = user_input
    config = {
        "configurable": {"thread_id": state["session_id"]},
        "recursion_limit": 8,
    }

    # Correlate every model run and evidence event produced while handling this
    # turn under one interaction id, so the turn can be reconstructed as a trace
    # (Phase 17 observability). The governance scope caps model calls per turn
    # and records which models answered (ADR-0035).
    with (
        interaction_scope(session_id=state["session_id"]) as interaction_id,
        governance.turn_scope() as answered_by,
    ):
        # Remember which interactions ran under this session so the trace
        # assembler can join the session's model runs (model_runs has no
        # session_id column). Also expose the id on the state for evidence.
        state["interaction_id"] = interaction_id
        _link_interaction(state["user_id"], state["session_id"], interaction_id, state)
        reply = ""
        saw_conversation = False
        async for update in _graph.astream(state, config):
            for node_update in update.values():
                if not isinstance(node_update, dict):
                    continue
                for key, value in node_update.items():
                    if key == "messages":
                        state["messages"] = state.get("messages", []) + value
                    else:
                        state[key] = value  # type: ignore[literal-required]
                if node_update.get("agent_response"):
                    reply = node_update["agent_response"]
            if "conversation" in update:
                saw_conversation = True
            # Stop after one full analysis cycle (conversation -> ... ->
            # evaluator) so the evaluator's difficulty signal is available for
            # adaptation.
            if saw_conversation and "evaluator" in update:
                break

        # Adaptive difficulty: adjust the effective level/guidance from the
        # evaluator's signal so the next turn is calibrated to the learner.
        adjustment = adaptive_node(state)
        state["cefr_level"] = adjustment["cefr_level"]
        state["current_scenario"] = adjustment["current_scenario"]
        models = state.get("llm_models", [])
        state["llm_models"] = models + [m for m in answered_by if m not in models]

    persist_snapshot(state)
    return reply or "..."


def _link_interaction(
    user_id: str, session_id: str, interaction_id: str, state: LearnerState
) -> None:
    """Persist the session<->interaction link (never breaks a turn)."""
    try:
        from src.observability.links import record_link

        turn_index = len([m for m in state.get("messages", []) if m.get("role") == "user"])
        record_link(session_id, interaction_id, user_id=user_id, turn_index=turn_index)
    except Exception:  # noqa: BLE001 - observability must never break a turn
        logger.debug("failed to record session interaction link", exc_info=True)


def export_for_user(user_id: str) -> list[dict[str, Any]]:
    """Snapshot rows for the privacy export (the state JSON included)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT session_id, language, status, state_json, created_at, updated_at "
            "FROM active_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_for_user(user_id: str) -> int:
    """Delete the user's snapshots and cached sessions (account deletion)."""
    for key in [k for k in _active if k[0] == user_id]:
        drop_session(*key)
    with _conn() as conn:
        return int(
            conn.execute("DELETE FROM active_sessions WHERE user_id = ?", (user_id,)).rowcount
        )


def reset() -> None:
    """Clear all cached sessions (used by tests for isolation)."""
    _active.clear()
    _last_used.clear()
