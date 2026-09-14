"""Durability test: SQLite checkpointer persists session state across restarts."""

from __future__ import annotations

import aiosqlite
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.agents import conversation, cultural, evaluator, grammar, vocabulary
from src.config import settings
from src.llm.provider import LLMProvider
from src.orchestrator.graph import compile_graph


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        if json_mode:
            return '{"errors": [], "words": []}'
        return "¡Hola! Soy Ana."


def _state():
    return {
        "session_id": "persist-1",
        "language": "Spanish",
        "mode": "conversation",
        "messages": [],
        "current_scenario": {
            "persona": {"name": "Ana", "role": "waiter", "personality": "warm"},
            "location": "Madrid",
            "objectives": ["order food"],
            "context": "restaurant",
        },
        "current_persona": None,
        "grammar_errors": [],
        "new_vocabulary": [],
        "cultural_notes": [],
        "evaluation": None,
        "cefr_level": "A2",
        "vocabulary_known_count": 0,
        "grammar_weaknesses": [],
        "user_interests": [],
        "turn_count": 0,
        "should_end_session": False,
        "pending_reviews": [],
        "last_user_input": "Hola, una mesa para dos",
        "agent_response": "",
    }


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    provider = ScriptedProvider()
    for module in (conversation, grammar, vocabulary, cultural, evaluator):
        monkeypatch.setattr(module, "get_provider", lambda tier: provider)
    # Keep cultural-note persistence offline.
    monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)


async def test_state_persists_across_restart(tmp_path):
    db_file = str(tmp_path / "polyglot.db")
    config = {"configurable": {"thread_id": "persist-1"}, "recursion_limit": 6}

    # --- First "process": run until the evaluator finishes one full loop, so
    # the conversation super-step is durably checkpointed, then stop. ---
    from langgraph.errors import GraphRecursionError

    async with aiosqlite.connect(db_file) as conn:
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        app = compile_graph(checkpointer=saver)

        # Let the looping graph run to its recursion limit; every completed
        # super-step is checkpointed to SQLite along the way.
        try:
            async for _update in app.astream(_state(), config):
                pass
        except GraphRecursionError:
            pass

    # --- Second "process": brand-new saver on the SAME db file. ---
    async with aiosqlite.connect(db_file) as conn2:
        saver2 = AsyncSqliteSaver(conn2)
        app2 = compile_graph(checkpointer=saver2)

        snapshot = await app2.aget_state(config)

    # The conversation from the first process is restored.
    assert snapshot is not None
    messages = snapshot.values.get("messages", [])
    contents = [m["content"] for m in messages]
    assert "Hola, una mesa para dos" in contents
    assert "¡Hola! Soy Ana." in contents
    assert snapshot.values.get("turn_count", 0) >= 1


async def test_different_thread_is_empty(tmp_path):
    db_file = str(tmp_path / "polyglot.db")

    from langgraph.errors import GraphRecursionError

    async with aiosqlite.connect(db_file) as conn:
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        app = compile_graph(checkpointer=saver)

        cfg1 = {"configurable": {"thread_id": "persist-1"}, "recursion_limit": 6}
        try:
            async for _update in app.astream(_state(), cfg1):
                pass
        except GraphRecursionError:
            pass

        # A different thread_id has no checkpointed state.
        cfg2 = {"configurable": {"thread_id": "other-thread"}}
        snapshot = await app.aget_state(cfg2)
        assert snapshot.values == {} or snapshot.values.get("messages", []) == []
