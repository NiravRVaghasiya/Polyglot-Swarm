"""Active chat sessions for the API: durable, capped and recoverable.

Holds each user's live :class:`LearnerState` between HTTP requests (keyed by
``(user_id, session_id)``) and runs one conversation turn at a time.

**Reply first, analysis after.** :func:`run_turn` returns as soon as the
conversation node has replied. The analysis of that turn (grammar, vocabulary
and cultural agents, then the evaluator and the adaptive-difficulty step)
runs as a per-session background task:

- before turn N+1 starts, and before the session is finalized, turn N's
  analysis is awaited, so every turn is analyzed in order and the next reply
  is pitched with the evaluator's signal, as before;
- analysis results are merged into the state in one step when the analysis
  finishes, so a cancelled analysis leaves no partial results. The snapshot
  marks the turn as pending (``pending_analysis_turn``) until then; a session
  rehydrated with that mark (after a restart) re-runs the analysis before its
  next turn or its finalization;
- an analysis failure is logged and skipped; it never fails a later turn;
- the hidden feedback a reply carries therefore covers the turns analyzed
  before it (``through_turn``): turn N's feedback arrives with the reply to
  turn N+1, and all of it is in the end-of-session report.

Database work on these paths runs in worker threads (``asyncio.to_thread``)
so a turn's SQLite I/O does not block other requests.

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

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.agents.adaptive import adaptive_node
from src.config import settings
from src.llm import governance
from src.observability import metrics
from src.observability.context import interaction_scope
from src.orchestrator.graph import REPLY_COMPONENTS, compile_analysis_graph, compile_turn_graph
from src.orchestrator.state import LearnerState
from src.util import utc_now_iso as _now

logger = logging.getLogger("polyglot.api.sessions")

# Compiled once and reused across requests. No checkpointer: this registry owns
# each session's state and resends it every turn (see compile_turn_graph).
# The reply graph is everything but analysis; the analysis graph is the
# grammar/vocabulary/cultural fan-out and the evaluator.
_reply_graph = compile_turn_graph(REPLY_COMPONENTS)
_analysis_graph = compile_analysis_graph()

_Key = tuple[str, str]

# (user_id, session_id) -> LearnerState (a cache over ``active_sessions``)
_active: dict[_Key, LearnerState] = {}
_last_used: dict[_Key, float] = {}
# The background analysis of each session's latest turn, while it runs.
_pending: dict[_Key, asyncio.Task[None]] = {}
# One turn at a time per session (a lock is bound to the loop that created it).
_turn_locks: dict[_Key, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = {}


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
    key = (user_id, session_id)
    _active.pop(key, None)
    _last_used.pop(key, None)
    _turn_locks.pop(key, None)
    task = _pending.pop(key, None)
    if task is not None and not task.done():
        task.cancel()


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
    active = await asyncio.to_thread(_active_ids, user_id)
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

    Waits for the last turn's analysis first (see :func:`wait_for_analysis`),
    so the report and the evidence include it. Then runs
    :func:`src.orchestrator.lifecycle.finalize_session`, marks the session
    ``finalized`` and clears its snapshot. On failure the claim is released
    (status back to ``active``) and the error re-raised, so the recovery task
    retries it.
    """
    from src.orchestrator.lifecycle import finalize_session

    state = state or await asyncio.to_thread(get_session, user_id, session_id)
    if state is None:
        return None
    await wait_for_analysis(state)
    if not await asyncio.to_thread(_claim, user_id, session_id):
        return None
    try:
        result = await finalize_session(state)
    except Exception:
        await asyncio.to_thread(_set_status, user_id, session_id, "active", clear_state=False)
        metrics.SESSION_EVENTS.inc(event="finalize_failed")
        raise
    await asyncio.to_thread(_set_status, user_id, session_id, "finalized", clear_state=True)
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

    def _scan() -> tuple[int, list[Any]]:
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
        return int(released), list(rows)

    released, rows = await asyncio.to_thread(_scan)
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


@dataclass(frozen=True)
class TurnResult:
    """A turn's reply and the hidden feedback known when it was given."""

    reply: str
    #: ``grammar``, ``vocabulary`` and ``cultural`` accumulated over the
    #: session's analyzed turns, and ``through_turn``: how many turns that
    #: covers (the current turn is still being analyzed).
    feedback: dict[str, Any]


def _turn_lock(key: _Key) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    entry = _turn_locks.get(key)
    if entry is None or entry[0] is not loop:
        entry = (loop, asyncio.Lock())
        _turn_locks[key] = entry
    return entry[1]


def _merge(target: dict[str, Any], update: dict[str, Any]) -> None:
    """Merge one node's partial update (``messages`` is append-only)."""
    for key, value in update.items():
        if key == "messages":
            target["messages"] = target.get("messages", []) + value
        else:
            target[key] = value


def _note_models(state: LearnerState, answered_by: list[str]) -> None:
    models = state.get("llm_models", [])
    state["llm_models"] = models + [m for m in answered_by if m not in models]


def _feedback(state: LearnerState) -> dict[str, Any]:
    return {
        "grammar": [dict(e) for e in state.get("grammar_errors", [])],
        "vocabulary": [dict(v) for v in state.get("new_vocabulary", [])],
        "cultural": list(state.get("cultural_notes", [])),
        "through_turn": state.get("analyzed_turns", 0),
    }


async def _analyze(state: LearnerState, turn: int, answered_by: list[str]) -> None:
    """Analyze the latest turn and merge the results into ``state`` at once.

    Runs the analysis graph (grammar, vocabulary, cultural, then evaluator)
    and the adaptive-difficulty step on the state as the reply left it. A
    failure is logged and the turn's analysis skipped; cancellation leaves
    the state untouched, still marked pending, so it is re-run later.
    """
    config = {"configurable": {"thread_id": state["session_id"]}, "recursion_limit": 8}
    updates: dict[str, Any] = {}
    try:
        async for update in _analysis_graph.astream(state, config):
            for node_update in update.values():
                if isinstance(node_update, dict):
                    _merge(updates, node_update)
        # Adaptive difficulty: adjust the effective level/guidance from the
        # evaluator's signal so the next turn is calibrated to the learner.
        adjustment = adaptive_node({**state, **updates})  # type: ignore[typeddict-item]
    except Exception:
        logger.exception(
            "analysis of turn %d failed for session %s; skipped", turn, state["session_id"]
        )
        metrics.SESSION_EVENTS.inc(event="analysis_failed")
        state.pop("pending_analysis_turn", None)
        await asyncio.to_thread(persist_snapshot, state)
        return
    _merge(state, updates)  # type: ignore[arg-type]
    state["cefr_level"] = adjustment["cefr_level"]
    state["current_scenario"] = adjustment["current_scenario"]
    _note_models(state, answered_by)
    state["analyzed_turns"] = turn
    state.pop("pending_analysis_turn", None)
    await asyncio.to_thread(persist_snapshot, state)


async def wait_for_analysis(state: LearnerState) -> None:
    """Make sure the session's latest turn has been analyzed.

    Awaits the background analysis if it is running in this event loop.
    If the turn is still marked pending without a running task (the process
    restarted, or the task was cancelled), the analysis is run now.
    """
    key = (state["user_id"], state["session_id"])
    task = _pending.pop(key, None)
    if task is not None and not task.done() and task.get_loop() is asyncio.get_running_loop():
        # asyncio.wait does not raise the task's exception or cancellation;
        # it raises only if this caller is cancelled.
        await asyncio.wait({task})
    turn = state.get("pending_analysis_turn")
    if turn is None:
        return
    with (
        interaction_scope(session_id=state["session_id"]),
        governance.turn_scope() as answered_by,
    ):
        await _analyze(state, turn, answered_by)


async def run_turn(state: LearnerState, user_input: str) -> TurnResult:
    """Run one turn: reply now, analyze in the background.

    Waits for the previous turn's analysis, then runs the reply stage
    (router, then review or conversation) and returns once the conversation
    node has replied. The state (with the reply) is snapshotted before
    returning, marked ``pending_analysis_turn``; the turn's analysis then runs
    as a background task (see the module docstring). Callers that end the
    process after a turn must call :func:`wait_for_analysis` first, or the
    analysis re-runs when the session is next used.
    """
    key = (state["user_id"], state["session_id"])
    async with _turn_lock(key):
        await wait_for_analysis(state)
        feedback = _feedback(state)
        state["last_user_input"] = user_input
        config = {
            "configurable": {"thread_id": state["session_id"]},
            "recursion_limit": 8,
        }

        # Correlate every model run and evidence event produced while handling
        # this turn (its reply and its analysis) under one interaction id, so
        # the turn can be reconstructed as a trace (Phase 17 observability).
        # The governance scope caps model calls per turn and records which
        # models answered (ADR-0035); the background analysis inherits both.
        with (
            interaction_scope(session_id=state["session_id"]) as interaction_id,
            governance.turn_scope() as answered_by,
        ):
            # Remember which interactions ran under this session so the trace
            # assembler can join the session's model runs (model_runs has no
            # session_id column). Also expose the id on the state for evidence.
            state["interaction_id"] = interaction_id
            await asyncio.to_thread(
                _link_interaction, state["user_id"], state["session_id"], interaction_id, state
            )
            reply = ""
            replied = False
            async for update in _reply_graph.astream(state, config):
                for node_update in update.values():
                    if not isinstance(node_update, dict):
                        continue
                    _merge(state, node_update)  # type: ignore[arg-type]
                    if node_update.get("agent_response"):
                        reply = node_update["agent_response"]
                if "conversation" in update:
                    replied = True
                    break
            _note_models(state, answered_by)
            if replied:
                turn = int(state.get("turn_count", 0))
                state["pending_analysis_turn"] = turn
                await asyncio.to_thread(persist_snapshot, state)
                _pending[key] = asyncio.create_task(
                    _analyze(state, turn, answered_by),
                    name=f"analysis:{state['session_id']}:{turn}",
                )
            else:
                await asyncio.to_thread(persist_snapshot, state)

    return TurnResult(reply=reply or "...", feedback=feedback)


async def drain_pending(timeout: float = 30.0) -> int:
    """Wait (up to ``timeout``) for running analyses; returns how many ran.

    Called at shutdown. Anything still running is cancelled; its turn stays
    marked pending in the snapshot and is analyzed when the session is next
    used.
    """
    tasks = [t for t in _pending.values() if not t.done()]
    if not tasks:
        return 0
    _done, still = await asyncio.wait(tasks, timeout=timeout)
    for task in still:
        task.cancel()
    return len(tasks)


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
    for key in [k for k in {*_active, *_pending} if k[0] == user_id]:
        drop_session(*key)
    with _conn() as conn:
        return int(
            conn.execute("DELETE FROM active_sessions WHERE user_id = ?", (user_id,)).rowcount
        )


def reset() -> None:
    """Clear all cached sessions (used by tests for isolation)."""
    for task in _pending.values():
        if not task.done():
            task.cancel()
    _pending.clear()
    _turn_locks.clear()
    _active.clear()
    _last_used.clear()
