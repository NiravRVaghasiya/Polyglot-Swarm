"""Fixtures for the Phase 5 production tests (ADR-0035)."""

from __future__ import annotations

import asyncio

import pytest

from src.llm.provider import LLMProvider
from tests.test_api.conftest import auth_client, client, mock_llm, temp_storage  # noqa: F401


class StubProvider(LLMProvider):
    """A provider with scripted behaviour: answer, fail, or hang."""

    def __init__(self, name: str, *, reply: str = "Hola", fail: Exception | None = None,
                 delay: float = 0.0, model: str = "stub-1") -> None:  # fmt: skip
        self.name = name
        self.model = model
        self.reply = reply
        self.fail = fail
        self.delay = delay
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail
        if json_mode:
            return '{"errors": [], "words": [], "notes": [], "transfers": []}'
        return self.reply


def register(api, name: str) -> tuple[dict[str, str], str]:
    resp = api.post("/api/v1/auth/register", json={"username": name, "password": "correct-horse-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


@pytest.fixture
def two_users(client):  # noqa: F811
    a_headers, a_id = register(client, "learner-a")
    b_headers, b_id = register(client, "learner-b")
    return client, (a_headers, a_id), (b_headers, b_id)
