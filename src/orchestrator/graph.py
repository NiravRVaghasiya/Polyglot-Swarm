"""LangGraph state machine — the core orchestration graph.

This module defines the agent graph topology:
    Router → Conversation → [Grammar, Vocabulary, Cultural] (parallel) → Evaluator → Router

The graph supports checkpointing for session persistence and
parallel fan-out for concurrent agent processing.

Phase 19 (learning-science experiment platform) adds :func:`build_graph`'s
``components`` parameter: an ablation study needs to compare which
architectural pieces actually create learning value (conversation alone vs.
+FSRS vs. +grammar/vocab/evaluator analysis vs. the full system), so the same
node functions are reused but selectively wired rather than duplicated into
parallel graph-building modules.
"""

from collections.abc import Hashable
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

#: The optional architectural components an ablation arm can include, beyond
#: the always-present router/conversation/session_end. Named after what each
#: adds, not the plan's A-E letters, so a caller can mix-and-match rather than
#: only pick from five fixed points (the letters are provided as presets below).
AblationComponent = str  # "analysis" | "review"

#: The plan's five-arm ablation ladder (Phase 19), spelled out as which
#: optional components each arm includes. "analysis" = grammar/vocabulary/
#: cultural/evaluator (what feeds the learner model with evidence); "review" =
#: FSRS spaced repetition. Memory/persistence (arm B) is not a graph-topology
#: concern — it happens in ``src.orchestrator.lifecycle`` around the graph
#: regardless of which nodes ran — so arms A and B share the same topology and
#: are distinguished by whether the caller persists evidence/snapshots, not by
#: which nodes are wired here.
ABLATION_ARMS: dict[str, frozenset[AblationComponent]] = {
    "A": frozenset(),  # conversation only
    "B": frozenset(),  # conversation + memory (same topology as A; see above)
    "C": frozenset({"review"}),  # + FSRS
    "D": frozenset({"analysis"}),  # + learner model (grammar/vocab/cultural/evaluator)
    "E": frozenset({"analysis", "review"}),  # full system
}


def build_graph(
    components: frozenset[AblationComponent] | None = None,
) -> StateGraph[LearnerState, None, LearnerState, LearnerState]:
    """Build and compile the LangGraph agent orchestration graph.

    Default topology (``components=None``, i.e. every component enabled):
        entry → router → (conversation | review | session_end)
        conversation → [grammar, vocabulary, cultural] (parallel fan-out)
        [grammar, vocabulary, cultural] → evaluator (fan-in)
        evaluator → router (loop back for next turn)
        review → router

    Args:
        components: Which optional architectural pieces to include, for an
            ablation study (Phase 19). ``None`` (the default) includes
            everything — identical to the graph before this parameter
            existed, so no existing caller's behavior changes. Pass a subset
            of ``{"analysis", "review"}`` (see :data:`ABLATION_ARMS` for the
            plan's named arms) to build a stripped-down comparison arm:
            without ``"analysis"``, conversation routes straight to the
            router (no grammar/vocabulary/cultural/evaluator, so no evidence
            reaches the learner model); without ``"review"``, the review node
            is omitted and the router always chooses conversation.

    Returns:
        Compiled LangGraph StateGraph ready for invocation.
    """
    enabled = _ALL_COMPONENTS if components is None else components
    graph = StateGraph(LearnerState)

    # --- Define nodes ---
    graph.add_node("router", router_node)
    graph.add_node("conversation", conversation_node)
    graph.add_node("session_end", session_end_node)
    if "analysis" in enabled:
        graph.add_node("grammar", grammar_node)
        graph.add_node("vocabulary", vocabulary_node)
        graph.add_node("cultural", cultural_node)
        graph.add_node("evaluator", evaluator_node)
    if "review" in enabled:
        graph.add_node("review", review_node)

    # --- Define edges ---
    # Entry point
    graph.set_entry_point("router")

    # Router dispatches to mode. Without "review" there is no review node to
    # route to, so route_by_mode's "review" branch would dead-end — the
    # router itself only ever returns "review" when pending_reviews is
    # non-empty, so an ablation arm without FSRS simply never populates that
    # queue (see lifecycle/CLI/API callers), but we still only wire the edge
    # when the node exists, to fail fast (KeyError) rather than silently if
    # that assumption is ever violated.
    routes: dict[Hashable, str] = {"conversation": "conversation", "end": "session_end"}
    if "review" in enabled:
        routes["review"] = "review"
    graph.add_conditional_edges("router", route_by_mode, routes)

    if "analysis" in enabled:
        # After conversation, fan out to analysis agents (parallel).
        graph.add_edge("conversation", "grammar")
        graph.add_edge("conversation", "vocabulary")
        graph.add_edge("conversation", "cultural")
        # All analysis agents feed into evaluator (fan-in).
        graph.add_edge("grammar", "evaluator")
        graph.add_edge("vocabulary", "evaluator")
        graph.add_edge("cultural", "evaluator")
        # Evaluator loops back to router for next turn.
        graph.add_edge("evaluator", "router")
    else:
        # No analysis stage: conversation's reply is the whole turn.
        graph.add_edge("conversation", "router")

    if "review" in enabled:
        # Review mode loops back to router.
        graph.add_edge("review", "router")

    # Session end terminates
    graph.add_edge("session_end", END)

    return graph


_ALL_COMPONENTS: frozenset[AblationComponent] = frozenset({"analysis", "review"})


def build_ablation_graph(arm: str) -> StateGraph[LearnerState, None, LearnerState, LearnerState]:
    """Build the graph for one of the plan's five named ablation arms (A-E).

    A thin, self-documenting wrapper over :func:`build_graph` for the specific
    comparison the plan calls out (Phase 19): which architectural components
    actually create learning value. Arm "E" is exactly :func:`build_graph`'s
    default (the production graph).
    """
    if arm not in ABLATION_ARMS:
        raise ValueError(f"unknown ablation arm {arm!r}; expected one of {sorted(ABLATION_ARMS)}")
    return build_graph(ABLATION_ARMS[arm])


def session_end_node(state: LearnerState) -> dict[str, Any]:
    """Compile the end-of-session report from all agents' outputs.

    Delegates to the shared report builder so the graph's terminal report and
    the lifecycle's :func:`finalize_session` report stay identical (grammar,
    vocabulary, cultural, CEFR, and cross-language transfer sections).
    """
    from src.orchestrator.lifecycle import build_session_report

    report = build_session_report(state)
    return {"agent_response": report, "should_end_session": True}


def compile_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    components: frozenset[AblationComponent] | None = None,
) -> Any:
    """Compile the graph with a checkpointer for session persistence.

    Args:
        checkpointer: A LangGraph checkpointer. Defaults to an in-memory
            ``MemorySaver`` (handy for tests and sync usage). Pass a SQLite
            saver (see :func:`compile_graph_async`) for durable sessions.
        components: Forwarded to :func:`build_graph` (Phase 19 ablation
            studies); ``None`` builds the full production graph.
    """
    graph = build_graph(components)
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
