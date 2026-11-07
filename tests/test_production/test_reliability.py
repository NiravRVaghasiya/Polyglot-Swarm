"""Provider failures, budgets, durable sessions, recovery and idempotency (R1-R3, R12, R13)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from src.config import settings
from src.evidence import store as evidence_store
from src.llm import governance
from src.llm.factory import RoutingProvider
from src.llm.governance import BudgetExceededError
from src.llm.provider import Message
from src.llm.reliability import CircuitBreaker, RetryPolicy
from src.observability import metrics
from src.observability.context import set_principal
from tests.test_production.conftest import StubProvider

MSG = [Message("user", "hola")]


def _router(*providers, retries=0):
    return RoutingProvider(
        list(providers),
        tier="primary",
        retry_policy=RetryPolicy(max_retries=retries, base_delay=0, max_delay=0),
        circuit_breaker=CircuitBreaker(failure_threshold=99),
    )


@pytest.fixture
def db(temp_storage):
    from src.memory import schema

    schema.init_all()
    set_principal(None)
    yield temp_storage
    set_principal(None)


class TestProviderFailures:
    def test_a_hung_provider_times_out_and_fails_over(self, db, monkeypatch):
        monkeypatch.setattr(settings, "llm_timeout_seconds", 0.05)
        slow = StubProvider("slow", delay=5.0)
        fast = StubProvider("fast", reply="ok")
        before = metrics.LLM_CALLS.value(provider="slow", tier="primary", outcome="timeout")
        reply = asyncio.run(_router(slow, fast, retries=1).generate(MSG))
        assert reply == "ok" and slow.calls == 2  # retried once, then failed over
        after = metrics.LLM_CALLS.value(provider="slow", tier="primary", outcome="timeout")
        assert after - before == 2

    def test_fallback_is_recorded_on_the_answer(self, db):
        down = StubProvider("primary-down", fail=ConnectionError("down"))
        backup = StubProvider("ollama", reply="ok", model="llama3.1:8b")
        with governance.turn_scope() as answered:
            asyncio.run(_router(down, backup).generate(MSG))
        assert answered == ["ollama:llama3.1:8b (fallback)"]

    def test_fallback_model_reaches_evidence_provenance(self):
        from src.evidence.extractor import extract_from_state

        state = {
            "user_id": "u", "language": "Spanish", "session_id": "s", "mode": "conversation",
            "messages": [{"role": "user", "content": "yo soy hambre"}],
            "grammar_errors": [], "new_vocabulary": [],
            "llm_models": ["claude:claude-sonnet-5-5", "ollama:llama3.1:8b (fallback)"],
        }  # fmt: skip
        events = extract_from_state(state)
        assert events and all("(fallback)" in (e.model_version or "") for e in events)


class TestBudgets:
    def test_user_daily_budget_stops_calls_without_failover(self, db, monkeypatch):
        monkeypatch.setattr(settings, "llm_user_daily_calls", 2)
        set_principal("u-budget")
        first, second = StubProvider("a"), StubProvider("b")
        router = _router(first, second)
        asyncio.run(router.generate(MSG))
        asyncio.run(router.generate(MSG))
        with pytest.raises(BudgetExceededError) as exc:
            asyncio.run(router.generate(MSG))
        assert exc.value.scope == "user" and first.calls == 2 and second.calls == 0
        # Another learner is unaffected.
        set_principal("u-other")
        assert asyncio.run(router.generate(MSG)) == "Hola"

    def test_global_budget_and_turn_cap(self, db, monkeypatch):
        monkeypatch.setattr(settings, "llm_global_daily_budget_usd", 0.001)
        governance.record_usage(0.002)
        with pytest.raises(BudgetExceededError, match="deployment"):
            asyncio.run(_router(StubProvider("a")).generate(MSG))
        monkeypatch.setattr(settings, "llm_global_daily_budget_usd", 0.0)
        monkeypatch.setattr(settings, "llm_max_calls_per_turn", 2)
        router = _router(StubProvider("a"))
        with governance.turn_scope(), pytest.raises(BudgetExceededError) as exc:  # noqa: PT012
            for _ in range(3):
                asyncio.run(router.generate(MSG))
        assert exc.value.scope == "turn"

    def test_chat_returns_429_on_budget_and_records_nothing(self, auth_client, monkeypatch):
        from src.agents import conversation

        client, headers, user_id = auth_client
        monkeypatch.setattr(settings, "llm_user_daily_calls", 1)
        monkeypatch.setattr(conversation, "get_provider", lambda tier: _router(StubProvider("a")))
        governance.record_usage(0.0)  # no principal: global only
        set_principal(user_id)
        governance.record_usage(0.0)  # this learner has used their one call
        set_principal(None)
        sid = client.post("/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers)
        resp = client.post(
            "/api/v1/chat", json={"session_id": sid.json()["session_id"], "message": "hola"},
            headers=headers,
        )  # fmt: skip
        assert resp.status_code == 429 and resp.json()["detail"]["code"] == "budget_exceeded"
        assert evidence_store.active_events(user_id, "Spanish") == []


class TestOutages:
    def test_total_outage_degrades_without_creating_graded_evidence(self, auth_client, monkeypatch):
        from src.agents import conversation, cultural, evaluator, grammar, transfer, vocabulary

        client, headers, user_id = auth_client
        down = _router(StubProvider("down", fail=ConnectionError("outage")))
        for module in (conversation, grammar, vocabulary, cultural, evaluator, transfer):
            monkeypatch.setattr(module, "get_provider", lambda tier, p=down: p)
        monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)
        sid = client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
        ).json()["session_id"]
        resp = client.post(
            "/api/v1/chat", json={"session_id": sid, "message": "yo soy hambre"}, headers=headers
        )
        assert resp.status_code == 200 and resp.json()["hidden_feedback"]["grammar"] == []
        assert client.post(f"/api/v1/sessions/{sid}/end", headers=headers).status_code == 200
        events = evidence_store.active_events(user_id, "Spanish")
        # Only exposure (the learner spoke); no correctness judgement was invented.
        assert events and {e["event_type"] for e in events} <= {"TURN_COMPLETED"}

    def test_malformed_structured_output_creates_no_grammar_evidence(self, db):
        from src.agents import grammar

        bad = _router(StubProvider("junk", reply="not json at all"))
        asyncio.run(asyncio.sleep(0))
        state = {"last_user_input": "yo soy hambre", "language": "Spanish", "messages": [],
                 "grammar_errors": [], "cefr_level": "A2"}  # fmt: skip
        original = grammar.get_provider
        try:
            grammar.get_provider = lambda tier: bad  # type: ignore[assignment]
            out = asyncio.run(grammar.grammar_node(state))  # type: ignore[arg-type]
        finally:
            grammar.get_provider = original
        assert out["grammar_errors"] == []


def _start(client, headers):
    return client.post(
        "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
    ).json()["session_id"]


def _age_session(session_id: str, hours: float) -> None:
    from src.memory.db import get_connection

    old = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE active_sessions SET updated_at = ? WHERE session_id = ?", (old, session_id)
        )


class TestDurableSessions:
    def test_a_session_survives_a_process_restart(self, auth_client, mock_llm):
        from src.api import sessions

        client, headers, _ = auth_client
        sid = _start(client, headers)
        client.post("/api/v1/chat", json={"session_id": sid, "message": "hola"}, headers=headers)
        sessions.reset()  # the in-memory cache is gone, as after a restart
        state = client.get(f"/api/v1/sessions/{sid}/state", headers=headers)
        assert state.status_code == 200 and state.json()["turn_count"] == 1
        chat = {"session_id": sid, "message": "otra vez"}
        assert client.post("/api/v1/chat", json=chat, headers=headers).status_code == 200

    def test_abandoned_sessions_are_finalized_by_maintenance(self, auth_client, mock_llm):
        from src.api import sessions
        from src.memory.db import get_connection
        from src.ops.maintenance import run_maintenance

        client, headers, user_id = auth_client
        sid = _start(client, headers)
        client.post("/api/v1/chat", json={"session_id": sid, "message": "hola"}, headers=headers)
        sessions.reset()
        _age_session(sid, settings.session_idle_finalize_hours + 1)
        report = asyncio.run(run_maintenance())
        assert report["sessions"]["finalized"] == 1
        assert evidence_store.active_events(user_id, "Spanish")  # learning data kept
        with get_connection() as conn:
            row = conn.execute(
                "SELECT status, state_json FROM active_sessions WHERE session_id = ?", (sid,)
            ).fetchone()
        assert row["status"] == "finalized" and row["state_json"] is None
        # A second run finds nothing to do (idempotent).
        assert asyncio.run(run_maintenance())["sessions"]["finalized"] == 0

    def test_a_session_is_finalized_once(self, auth_client, mock_llm):
        from src.api import sessions

        client, headers, user_id = auth_client
        sid = _start(client, headers)
        client.post("/api/v1/chat", json={"session_id": sid, "message": "hola"}, headers=headers)
        state = sessions.get_session(user_id, sid)

        async def both():
            return await asyncio.gather(
                sessions.finalize(user_id, sid, state=state),
                sessions.finalize(user_id, sid, state=state),
            )

        results = asyncio.run(both())
        assert sum(r is not None for r in results) == 1
        assert client.post(f"/api/v1/sessions/{sid}/end", headers=headers).status_code == 404

    def test_a_failed_finalize_is_retried_by_recovery(self, auth_client, mock_llm, monkeypatch):
        from src.api import sessions
        from src.orchestrator import lifecycle

        client, headers, user_id = auth_client
        sid = _start(client, headers)

        async def crash(state, **kw):
            raise RuntimeError("disk full")

        original = lifecycle.finalize_session
        monkeypatch.setattr(lifecycle, "finalize_session", crash)
        with pytest.raises(RuntimeError):
            asyncio.run(sessions.finalize(user_id, sid))
        monkeypatch.setattr(lifecycle, "finalize_session", original)
        _age_session(sid, settings.session_idle_finalize_hours + 1)
        assert asyncio.run(sessions.recover_idle_sessions())["finalized"] == 1

    def test_the_active_session_cap_finalizes_the_oldest(self, auth_client, mock_llm, monkeypatch):
        from src.api import sessions

        client, headers, user_id = auth_client
        monkeypatch.setattr(settings, "max_active_sessions_per_user", 2)
        first = _start(client, headers)
        _age_session(first, 1)
        _start(client, headers)
        _start(client, headers)
        assert sessions.get_session(user_id, first) is None
        assert len(sessions._active_ids(user_id)) == 2

    def test_snapshots_are_exported_and_deleted_with_the_account(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        _start(client, headers)
        export = client.get("/api/v1/privacy/export", headers=headers).json()
        assert len(export["data"]["active_sessions"]) == 1
        deleted = client.delete("/api/v1/privacy/data", headers=headers).json()
        assert deleted["deleted"]["active_sessions"] == 1


class TestIdempotency:
    def _review(self, client, headers, key, word="gato"):
        return client.post(
            "/api/v1/review/submit",
            json={"word": word, "correct": True},
            headers={**headers, "Idempotency-Key": key},
        )

    def test_a_retried_review_is_recorded_once(self, auth_client):
        client, headers, user_id = auth_client
        first = self._review(client, headers, "retry-key-001")
        again = self._review(client, headers, "retry-key-001")
        assert first.status_code == again.status_code == 200
        assert first.json() == again.json()
        events = [
            e for e in evidence_store.active_events(user_id, "Spanish") if e["item_id"] == "gato"
        ]
        assert len(events) == 1

    def test_reusing_a_key_for_another_request_is_refused(self, auth_client):
        client, headers, _ = auth_client
        self._review(client, headers, "retry-key-002")
        assert self._review(client, headers, "retry-key-002", word="perro").status_code == 422

    def test_keys_are_per_user(self, two_users):
        client, (a, _), (b, _) = two_users
        assert self._review(client, a, "shared-key-01").status_code == 200
        assert self._review(client, b, "shared-key-01").status_code == 200

    def test_a_failed_request_releases_its_key(self, auth_client, monkeypatch):
        from src.agents import review

        client, headers, _ = auth_client
        original = review.grade_review
        monkeypatch.setattr(review, "grade_review", lambda *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            self._review(client, headers, "retry-key-003")
        monkeypatch.setattr(review, "grade_review", original)
        assert self._review(client, headers, "retry-key-003").status_code == 200

    def test_a_retried_chat_message_runs_once(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        sid = _start(client, headers)
        body = {"session_id": sid, "message": "hola"}
        h = {**headers, "Idempotency-Key": "chat-key-0001"}
        assert client.post("/api/v1/chat", json=body, headers=h).status_code == 200
        assert client.post("/api/v1/chat", json=body, headers=h).status_code == 200
        state = client.get(f"/api/v1/sessions/{sid}/state", headers=headers).json()
        assert state["turn_count"] == 1
