"""Shared fixtures for API tests: isolated storage + TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


@pytest.fixture
def client(temp_storage):
    from src.api import auth, sessions
    from src.api.app import create_app

    sessions.reset()
    # The auth rate limiters are process-global (Phase 21) so every test gets
    # a clean budget instead of inheriting counters from earlier tests that
    # happened to share a client key (TestClient requests all appear to come
    # from the same synthetic host).
    auth.login_rate_limiter.reset()
    auth.register_rate_limiter.reset()
    return TestClient(create_app())


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock every agent's LLM provider so graph turns run offline.

    JSON-mode agents get a payload valid for grammar/vocab (empty lists) and
    cultural/evaluator/transfer parsers tolerate missing keys.
    """
    from src.agents import (
        conversation,
        cultural,
        evaluator,
        grammar,
        transfer,
        vocabulary,
    )
    from src.llm.provider import LLMProvider

    class ScriptedProvider(LLMProvider):
        name = "scripted"

        def is_available(self) -> bool:
            return True

        async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
            if json_mode:
                return '{"errors": [], "words": [], "notes": [], "transfers": []}'
            return "¡Hola! ¿En qué puedo ayudar?"

    provider = ScriptedProvider()
    for module in (conversation, grammar, vocabulary, cultural, evaluator, transfer):
        monkeypatch.setattr(module, "get_provider", lambda tier: provider)
    monkeypatch.setattr(cultural, "_persist_notes", lambda state, notes: None)
    return provider


@pytest.fixture
def auth_client(client):
    """A TestClient with a registered+authenticated user; returns (client, headers, user_id)."""
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "s3cret"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return client, headers, body["user_id"]
