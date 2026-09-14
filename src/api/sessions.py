"""In-process active-session registry and turn runner for the API.

Holds each user's live :class:`LearnerState` between HTTP requests (keyed by
``(user_id, session_id)``) and runs a single conversation turn through the
compiled graph. Durable persistence still happens via ``finalize_session`` when
a session ends; this registry only tracks in-flight sessions.
"""

from __future__ import annotations

from src.agents.adaptive import adaptive_node
from src.orchestrator.graph import compile_graph
from src.orchestrator.state import LearnerState

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
        # Stop after one full analysis cycle (conversation -> ... -> evaluator)
        # so the evaluator's difficulty signal is available for adaptation.
        if saw_conversation and "evaluator" in update:
            break

    # Adaptive difficulty: adjust the effective level/guidance from the
    # evaluator's signal so the next turn is calibrated to the learner.
    adjustment = adaptive_node(state)
    state["cefr_level"] = adjustment["cefr_level"]
    state["current_scenario"] = adjustment["current_scenario"]

    return reply or "..."


def reset() -> None:
    """Clear all active sessions (used by tests for isolation)."""
    _active.clear()
