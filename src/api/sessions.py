"""In-process active-session registry and turn runner for the API.

Holds each user's live :class:`LearnerState` between HTTP requests (keyed by
``(user_id, session_id)``) and runs a single conversation turn through the
compiled graph. Durable persistence still happens via ``finalize_session`` when
a session ends; this registry only tracks in-flight sessions.
"""

from __future__ import annotations

import logging

from src.agents.adaptive import adaptive_node
from src.observability.context import interaction_scope
from src.orchestrator.graph import compile_graph
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.api.sessions")

# Compiled once and reused across requests.
_graph = compile_graph()

# (user_id, session_id) -> LearnerState
_active: dict[tuple[str, str], LearnerState] = {}


def register_session(user_id: str, state: LearnerState) -> None:
    _active[(user_id, state["session_id"])] = state


def get_session(user_id: str, session_id: str) -> LearnerState | None:
    return _active.get((user_id, session_id))


def drop_session(user_id: str, session_id: str) -> None:
    _active.pop((user_id, session_id), None)


async def run_turn(state: LearnerState, user_input: str) -> str:
    """Run one conversation turn through the graph, mutating ``state`` in place.

    Streams graph node updates and stops once the conversation node has produced
    its reply, merging each node's partial update back into ``state``. Returns
    the assistant reply.
    """
    state["last_user_input"] = user_input
    config = {
        "configurable": {"thread_id": state["session_id"]},
        "recursion_limit": 8,
    }

    # Correlate every model run and evidence event produced while handling this
    # turn under one interaction id, so the turn can be reconstructed as a trace
    # (Phase 17 observability).
    with interaction_scope(session_id=state["session_id"]) as interaction_id:
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


def reset() -> None:
    """Clear all active sessions (used by tests for isolation)."""
    _active.clear()
