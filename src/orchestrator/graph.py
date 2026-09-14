"""LangGraph state machine — the core orchestration graph.

This module defines the agent graph topology:
    Router → Conversation → [Grammar, Vocabulary, Cultural] (parallel) → Evaluator → Router

The graph supports checkpointing for session persistence and
parallel fan-out for concurrent agent processing.
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.conversation import conversation_node
from src.agents.cultural import cultural_node
from src.agents.evaluator import evaluator_node
from src.agents.grammar import grammar_node
from src.agents.srs import review_node
from src.agents.vocabulary import vocabulary_node
from src.orchestrator.router import route_by_mode, router_node
from src.orchestrator.state import LearnerState


def build_graph() -> StateGraph[LearnerState, None, LearnerState, LearnerState]:
    """Build and compile the LangGraph agent orchestration graph.

    Graph topology:
        entry → router → (conversation | review | session_end)
        conversation → [grammar, vocabulary, cultural] (parallel fan-out)
        [grammar, vocabulary, cultural] → evaluator (fan-in)
        evaluator → router (loop back for next turn)

    Returns:
        Compiled LangGraph StateGraph ready for invocation.
    """
    graph = StateGraph(LearnerState)

    # --- Define nodes ---
    graph.add_node("router", router_node)
    graph.add_node("conversation", conversation_node)
    graph.add_node("grammar", grammar_node)
    graph.add_node("vocabulary", vocabulary_node)
    graph.add_node("cultural", cultural_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("review", review_node)
    graph.add_node("session_end", session_end_node)

    # --- Define edges ---
    # Entry point
    graph.set_entry_point("router")

    # Router dispatches to mode
    graph.add_conditional_edges(
        "router",
        route_by_mode,
        {
            "conversation": "conversation",
            "review": "review",
            "end": "session_end",
        },
    )

    # After conversation, fan out to analysis agents (parallel)
    graph.add_edge("conversation", "grammar")
    graph.add_edge("conversation", "vocabulary")
    graph.add_edge("conversation", "cultural")

    # All analysis agents feed into evaluator (fan-in)
    graph.add_edge("grammar", "evaluator")
    graph.add_edge("vocabulary", "evaluator")
    graph.add_edge("cultural", "evaluator")

    # Evaluator loops back to router for next turn
    graph.add_edge("evaluator", "router")

    # Review mode loops back to router
    graph.add_edge("review", "router")

    # Session end terminates
    graph.add_edge("session_end", END)

    return graph


def session_end_node(state: LearnerState) -> dict[str, Any]:
    """Compile the end-of-session report from all agents' outputs.

    Delegates to the shared report builder so the graph's terminal report and
    the lifecycle's :func:`finalize_session` report stay identical (grammar,
    vocabulary, cultural, CEFR, and cross-language transfer sections).
    """
    from src.orchestrator.lifecycle import build_session_report

    report = build_session_report(state)
    return {"agent_response": report, "should_end_session": True}


def compile_graph(checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    """Compile the graph with a checkpointer for session persistence.

    Args:
        checkpointer: A LangGraph checkpointer. Defaults to an in-memory
            ``MemorySaver`` (handy for tests and sync usage). Pass a SQLite
            saver (see :func:`compile_graph_async`) for durable sessions.
    """
    graph = build_graph()
    if checkpointer is None:
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


async def compile_graph_async() -> Any:
    """Compile the graph with a durable SQLite checkpointer.

    Sessions checkpointed this way survive process restarts — resuming the same
    ``thread_id`` (session_id) restores the full conversation state.
    """
    from src.memory.checkpointer import build_async_checkpointer

    checkpointer = await build_async_checkpointer()
    return compile_graph(checkpointer=checkpointer)
