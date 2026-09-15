"""Phase 19 tests: the ablation-arm graph builder.

Verifies build_graph's optional components parameter and build_ablation_graph
wire the right nodes/edges for each of the plan's five named arms (A-E),
without changing the default (components=None) topology anyone already relies
on.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agents import conversation, cultural, evaluator, grammar, vocabulary
from src.llm.provider import LLMProvider
from src.orchestrator.graph import (
    ABLATION_ARMS,
    build_ablation_graph,
    build_graph,
    compile_graph,
)
from src.orchestrator.lifecycle import build_initial_state


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        if json_mode:
            return '{"errors": [], "words": [], "notes": [], "transfers": []}'
        return "¡Hola! ¿En qué puedo ayudarte?"


@pytest.fixture(autouse=True)
def _patch_llm(monkeypatch):
    provider = ScriptedProvider()
    for module in (conversation, grammar, vocabulary, cultural, evaluator):
        monkeypatch.setattr(module, "get_provider", lambda tier: provider)
    monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)


def _initial_state(session_id: str) -> dict:
    state = build_initial_state("u1", "Spanish", session_id=session_id)
    state["last_user_input"] = "Hola, quiero una mesa"
    return state


class TestBuildGraphDefaultUnchanged:
    def test_none_includes_every_node(self):
        graph = build_graph(None)
        assert set(graph.nodes) == {
            "router",
            "conversation",
            "grammar",
            "vocabulary",
            "cultural",
            "evaluator",
            "review",
            "session_end",
        }

    def test_default_call_with_no_args_matches_none(self):
        assert set(build_graph().nodes) == set(build_graph(None).nodes)


class TestAblationArms:
    def test_arm_a_conversation_only(self):
        graph = build_ablation_graph("A")
        assert set(graph.nodes) == {"router", "conversation", "session_end"}

    def test_arm_b_same_topology_as_a(self):
        # Memory/persistence (arm B) is not a graph-topology concern; it
        # happens around the graph regardless of which nodes ran.
        assert set(build_ablation_graph("A").nodes) == set(build_ablation_graph("B").nodes)

    def test_arm_c_adds_review_only(self):
        graph = build_ablation_graph("C")
        assert set(graph.nodes) == {"router", "conversation", "review", "session_end"}

    def test_arm_d_adds_analysis_only(self):
        graph = build_ablation_graph("D")
        assert set(graph.nodes) == {
            "router",
            "conversation",
            "grammar",
            "vocabulary",
            "cultural",
            "evaluator",
            "session_end",
        }

    def test_arm_e_is_the_full_system(self):
        assert set(build_ablation_graph("E").nodes) == set(build_graph(None).nodes)

    def test_unknown_arm_raises(self):
        with pytest.raises(ValueError, match="unknown ablation arm"):
            build_ablation_graph("Z")

    def test_every_named_arm_is_a_valid_frozenset_of_known_components(self):
        for components in ABLATION_ARMS.values():
            assert components <= {"analysis", "review"}


class TestAblationArmsRunATurn:
    """Each arm must actually compile and run a real turn, not just wire nodes."""

    async def _run_one_turn(self, arm: str) -> dict:
        graph = build_ablation_graph(arm).compile(checkpointer=MemorySaver())
        state = _initial_state(f"abl-{arm}")
        config = {"configurable": {"thread_id": f"abl-{arm}"}, "recursion_limit": 8}
        seen: dict[str, dict] = {}
        async for update in graph.astream(state, config):
            seen.update(update)
            if "conversation" in seen and ("router" in update or "evaluator" in update):
                break
        return seen

    async def test_arm_a_runs_conversation_and_returns_to_router(self):
        seen = await self._run_one_turn("A")
        assert "conversation" in seen
        assert seen["conversation"]["agent_response"]
        assert "grammar" not in seen and "evaluator" not in seen

    async def test_arm_d_runs_analysis_agents(self):
        seen = await self._run_one_turn("D")
        assert "conversation" in seen
        assert "grammar" in seen
        assert "vocabulary" in seen
        assert "cultural" in seen
        assert "evaluator" in seen

    async def test_arm_e_matches_default_graph_behavior(self):
        seen = await self._run_one_turn("E")
        assert "evaluator" in seen


class TestCompileGraphComponentsKwarg:
    async def test_compile_graph_forwards_components(self):
        app = compile_graph(components=ABLATION_ARMS["A"])
        state = _initial_state("compile-a")
        config = {"configurable": {"thread_id": "compile-a"}, "recursion_limit": 8}
        saw_conversation = False
        async for update in app.astream(state, config):
            if "conversation" in update:
                saw_conversation = True
            if saw_conversation and "router" in update:
                break
        assert saw_conversation

    def test_compile_graph_default_still_builds_full_graph(self):
        app = compile_graph()
        # LangGraph's compiled graph exposes the underlying node names via
        # get_graph(); the full system's nodes must all still be present.
        node_names = set(app.get_graph().nodes)
        assert {"grammar", "vocabulary", "cultural", "evaluator", "review"} <= node_names
