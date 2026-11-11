"""Reply first, analysis after (src.api.sessions.run_turn).

The reply is returned once the conversation node answers; the grammar,
vocabulary, cultural and evaluator nodes run as a background task that the
next turn and finalization wait for.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx
import pytest

from src.agents import conversation, cultural, evaluator, grammar, transfer, vocabulary
from src.llm.provider import LLMProvider

_TURN = re.compile(r"\bt(\d+)\b")


def _turn_of(messages: Any) -> int:
    """The turn marker ("t3") in the last message that mentions one."""
    for m in reversed(list(messages)):
        found = _TURN.findall(str(getattr(m, "content", m)))
        if found:
            return int(found[-1])
    return 0


class _Scripted(LLMProvider):
    """Turn-specific, deterministic answers per agent (so turns differ)."""

    name = "scripted"

    def __init__(self, role: str) -> None:
        self.role = role

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        n = _turn_of(messages)
        if self.role == "conversation":
            return f"respuesta {n}"
        if self.role == "grammar":
            return json.dumps(
                {
                    "errors": [
                        {
                            "original": f"yo es cansado t{n}",
                            "correction": "yo estoy cansado",
                            "rule": "ser_vs_estar",
                            "construction": "ser_vs_estar",
                            "classification": "wrong",
                            "severity": "moderate",
                            "confidence": 0.9,
                        }
                    ]
                }
            )
        if self.role == "vocabulary":
            return json.dumps({"words": [{"word": f"palabra{n}", "translation": f"word {n}"}]})
        return json.dumps({"notes": [], "transfers": []})


@pytest.fixture
def scripted(monkeypatch):
    for module, role in (
        (conversation, "conversation"),
        (grammar, "grammar"),
        (vocabulary, "vocabulary"),
        (cultural, "cultural"),
        (evaluator, "evaluator"),
        (transfer, "transfer"),
    ):
        provider = _Scripted(role)
        monkeypatch.setattr(module, "get_provider", lambda tier, p=provider: p)
    monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)


@pytest.fixture
async def api(temp_storage, scripted):
    """An async client in the test's event loop, so background tasks share it."""
    from src.api import auth, sessions
    from src.api.app import create_app
    from src.api.deps import user_work_limiter
    from src.memory import schema

    schema.init_all()
    sessions.reset()
    user_work_limiter.reset()
    auth.register_rate_limiter.reset()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/register", json={"username": "bob", "password": "pw-secret-1"}
        )
        body = resp.json()
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        yield client, headers, body["user_id"]
    sessions.reset()


@pytest.fixture
def gate(monkeypatch):
    """Block the grammar node until the returned event is set."""
    from src.api import sessions
    from src.orchestrator import graph

    event = asyncio.Event()
    real = graph.grammar_node

    async def blocked(state):
        await event.wait()
        return await real(state)

    monkeypatch.setattr(graph, "grammar_node", blocked)
    monkeypatch.setattr(sessions, "_analysis_graph", graph.compile_analysis_graph())
    return event


async def _start(client, headers) -> str:
    resp = await client.post(
        "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["session_id"])


async def _chat(client, headers, sid: str, text: str) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/chat", json={"session_id": sid, "message": text}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


class TestReplyBeforeAnalysis:
    async def test_reply_returns_while_analysis_is_blocked(self, api, gate):
        from src.api import sessions

        client, headers, user_id = api
        sid = await _start(client, headers)
        body = await asyncio.wait_for(_chat(client, headers, sid, "hola t1"), timeout=10)
        assert body["reply"] == "respuesta 1"
        assert not gate.is_set()
        assert body["hidden_feedback"]["through_turn"] == 0
        task = sessions._pending[(user_id, sid)]
        assert not task.done()

        gate.set()
        await asyncio.wait_for(task, timeout=10)
        state = sessions.get_session(user_id, sid)
        assert state["analyzed_turns"] == 1 and "pending_analysis_turn" not in state

        # Turn 1's feedback arrives with the reply to turn 2.
        body = await _chat(client, headers, sid, "ahora t2")
        assert body["hidden_feedback"]["through_turn"] == 1
        assert [e["original"] for e in body["hidden_feedback"]["grammar"]] == ["yo es cansado t1"]
        assert [w["word"] for w in body["hidden_feedback"]["vocabulary"]] == ["palabra1"]

    async def test_next_turn_waits_for_the_previous_analysis(self, api, gate):
        client, headers, _ = api
        sid = await _start(client, headers)
        await _chat(client, headers, sid, "hola t1")
        second = asyncio.create_task(_chat(client, headers, sid, "ahora t2"))
        await asyncio.sleep(0.2)
        assert not second.done()  # turn 2 is held until turn 1 is analyzed
        gate.set()
        body = await asyncio.wait_for(second, timeout=10)
        assert body["hidden_feedback"]["through_turn"] == 1

    async def test_end_waits_for_pending_analysis_and_persists_it(self, api, gate):
        from src.evidence import store

        client, headers, user_id = api
        sid = await _start(client, headers)
        await _chat(client, headers, sid, "hola t1")
        end = asyncio.create_task(client.post(f"/api/v1/sessions/{sid}/end", headers=headers))
        await asyncio.sleep(0.2)
        assert not end.done()
        gate.set()
        resp = await asyncio.wait_for(end, timeout=10)
        assert resp.status_code == 200, resp.text
        assert "yo es cansado t1" in resp.json()["report"]
        items = {e.get("item_id") for e in store.active_events(user_id, "Spanish")}
        assert "palabra1" in items

    async def test_analysis_failure_is_logged_and_the_next_turn_works(
        self, api, monkeypatch, caplog
    ):
        from src.api import sessions
        from src.orchestrator import graph

        async def broken(state):
            raise RuntimeError("evaluator exploded")

        monkeypatch.setattr(graph, "evaluator_node", broken)
        monkeypatch.setattr(sessions, "_analysis_graph", graph.compile_analysis_graph())
        client, headers, user_id = api
        sid = await _start(client, headers)
        await _chat(client, headers, sid, "hola t1")
        body = await _chat(client, headers, sid, "ahora t2")
        assert body["reply"] == "respuesta 2"
        assert body["hidden_feedback"]["through_turn"] == 0
        assert "analysis of turn 1 failed" in caplog.text
        state = sessions.get_session(user_id, sid)
        assert "pending_analysis_turn" in state  # turn 2 is pending, turn 1 was skipped
        assert state["pending_analysis_turn"] == 2

    async def test_restart_with_a_pending_turn_reruns_its_analysis(self, api, gate):
        from src.api import sessions

        client, headers, user_id = api
        sid = await _start(client, headers)
        await _chat(client, headers, sid, "hola t1")
        sessions.reset()  # the process dies: the task is gone, the snapshot stays
        gate.set()
        body = await _chat(client, headers, sid, "ahora t2")
        assert body["hidden_feedback"]["through_turn"] == 1
        assert [e["original"] for e in body["hidden_feedback"]["grammar"]] == ["yo es cansado t1"]


# --- equivalence with the synchronous flow -------------------------------------


async def _synchronous_turn(graph: Any, state: dict[str, Any], text: str) -> None:
    """The turn runner before reply-first: one stream until the evaluator."""
    from src.agents.adaptive import adaptive_node
    from src.llm import governance
    from src.observability.context import interaction_scope

    state["last_user_input"] = text
    config = {"configurable": {"thread_id": state["session_id"]}, "recursion_limit": 8}
    with (
        interaction_scope(session_id=state["session_id"]),
        governance.turn_scope() as answered_by,
    ):
        saw_conversation = False
        async for update in graph.astream(state, config):
            for node_update in update.values():
                if not isinstance(node_update, dict):
                    continue
                for key, value in node_update.items():
                    if key == "messages":
                        state["messages"] = state.get("messages", []) + value
                    else:
                        state[key] = value
            if "conversation" in update:
                saw_conversation = True
            if saw_conversation and "evaluator" in update:
                break
        adjustment = adaptive_node(state)
        state["cefr_level"] = adjustment["cefr_level"]
        state["current_scenario"] = adjustment["current_scenario"]
        models = state.get("llm_models", [])
        state["llm_models"] = models + [m for m in answered_by if m not in models]


def _evidence(user_id: str, session_id: str) -> list[tuple[Any, ...]]:
    from src.memory.db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM evidence WHERE user_id = ? ORDER BY rowid", (user_id,)
        ).fetchall()
    ignored = {"id", "event_id", "user_id", "session_id", "interaction_id", "created_at",
               "recorded_at", "fingerprint", "provenance", "trace_id"}  # fmt: skip
    # correlation_id hashes the session id: compare which events share one.
    groups: dict[Any, int] = {}
    out = []
    for row in rows:
        record = {k: row[k] for k in row.keys() if k not in ignored}
        if record.get("correlation_id") is not None:
            record["correlation_id"] = groups.setdefault(record["correlation_id"], len(groups))
        out.append(
            tuple(sorted((k, str(v).replace(session_id, "<sid>")) for k, v in record.items()))
        )
    return out


async def test_five_turns_record_the_same_evidence_and_report_as_the_synchronous_flow(
    temp_storage, scripted
):
    from src.api import sessions
    from src.memory import schema
    from src.orchestrator.graph import compile_turn_graph
    from src.orchestrator.lifecycle import build_initial_state, finalize_session

    schema.init_all()
    sessions.reset()
    turns = [f"mensaje t{i}" for i in range(1, 6)]

    sync_state = build_initial_state("u-sync", "Spanish", session_id="s-sync")
    full_graph = compile_turn_graph()
    for text in turns:
        await _synchronous_turn(full_graph, sync_state, text)
    sync_result = await finalize_session(sync_state)

    async_state = build_initial_state("u-async", "Spanish", session_id="s-async")
    sessions.register_session("u-async", async_state)
    replies = [(await sessions.run_turn(async_state, text)).reply for text in turns]
    async_result = await sessions.finalize("u-async", "s-async", state=async_state)

    assert replies == [f"respuesta {i}" for i in range(1, 6)]
    assert async_result is not None
    sync_evidence = _evidence("u-sync", "s-sync")
    assert len(sync_evidence) >= 10  # 5 grammar errors and 5 words, at least
    assert _evidence("u-async", "s-async") == sync_evidence
    assert async_result["persisted"] == sync_result["persisted"]
    assert async_result["report"] == sync_result["report"]
    for key in ("grammar_errors", "new_vocabulary", "cultural_notes", "cefr_level", "turn_count"):
        assert async_state[key] == sync_state[key], key


def _snapshot_rows(user_id: str) -> int:
    from src.memory.db import get_connection

    with get_connection() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM active_sessions WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
        )


class TestDeletionDuringAnalysis:
    async def test_deleting_the_account_stops_the_analysis_and_nothing_comes_back(self, api, gate):
        from src.api import sessions
        from src.memory import user_profile

        client, headers, user_id = api
        sid = await _start(client, headers)
        await _chat(client, headers, sid, "hola t1")
        task = sessions._pending[(user_id, sid)]

        resp = await client.delete("/api/v1/privacy/data", headers=headers)
        assert resp.status_code == 200, resp.text
        gate.set()
        await asyncio.sleep(0.2)

        assert task.cancelled()
        assert _snapshot_rows(user_id) == 0
        assert not user_profile.profile_exists(user_id)
        # The idle-session recovery has nothing to finalize for the user.
        outcome = await sessions.recover_idle_sessions(idle_hours=0)
        assert outcome["finalized"] == 0 and _snapshot_rows(user_id) == 0

    def test_a_late_snapshot_does_not_recreate_a_deleted_session(self, temp_storage):
        from src.api import sessions
        from src.memory import schema
        from src.orchestrator.lifecycle import build_initial_state

        schema.init_all()
        sessions.reset()
        state = build_initial_state("u-late", "Spanish", session_id="s-late")
        sessions.register_session("u-late", state)
        assert _snapshot_rows("u-late") == 1

        sessions.delete_for_user("u-late")
        sessions.persist_snapshot(state)  # a turn that finished after the deletion
        assert _snapshot_rows("u-late") == 0
