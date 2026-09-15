"""Phase 23 tests: conversation_node degrades gracefully on total LLM outage.

Before this, conversation_node had zero exception handling around
``await provider.generate(...)`` — if every provider in the routing chain
failed (all retries and failover exhausted), the exception propagated
uncaught and crashed the whole turn. Now a total outage produces a canned,
in-character fallback reply instead, so the session can continue.
"""

from __future__ import annotations

from src.agents import conversation
from src.llm.factory import NoProviderAvailableError
from src.llm.provider import LLMProvider


class AlwaysFailsProvider(LLMProvider):
    name = "always-fails"

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        raise NoProviderAvailableError("All providers failed for tier='primary'")


def _base_state(**overrides):
    state = {
        "session_id": "s1",
        "language": "Spanish",
        "mode": "conversation",
        "messages": [],
        "current_scenario": {"persona": {"name": "Ana", "role": "waiter"}},
        "cefr_level": "A2",
        "turn_count": 0,
        "last_user_input": "Hola, quiero una mesa",
        "agent_response": "",
    }
    state.update(overrides)
    return state


class TestTotalProviderOutage:
    async def test_returns_fallback_reply_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(conversation, "get_provider", lambda tier: AlwaysFailsProvider())

        result = await conversation.conversation_node(_base_state())

        assert result["agent_response"]  # non-empty — a real fallback string
        assert "Disculpa" in result["agent_response"]  # Spanish fallback

    async def test_turn_count_and_messages_still_advance(self, monkeypatch):
        monkeypatch.setattr(conversation, "get_provider", lambda tier: AlwaysFailsProvider())

        result = await conversation.conversation_node(_base_state(turn_count=3))

        assert result["turn_count"] == 4
        roles = [m["role"] for m in result["messages"]]
        assert roles == ["user", "assistant"]
        assert result["messages"][-1]["content"] == result["agent_response"]

    async def test_fallback_is_language_specific(self, monkeypatch):
        monkeypatch.setattr(conversation, "get_provider", lambda tier: AlwaysFailsProvider())

        polish_result = await conversation.conversation_node(_base_state(language="Polish"))
        italian_result = await conversation.conversation_node(_base_state(language="Italian"))
        english_result = await conversation.conversation_node(
            _base_state(language="Klingon")  # no mapping -> generic default
        )

        assert "Przepraszam" in polish_result["agent_response"]
        assert "Scusa" in italian_result["agent_response"]
        assert (
            english_result["agent_response"]
            == "Sorry, I didn't catch that. Could you say it again?"
        )

    async def test_unrelated_provider_error_also_degrades(self, monkeypatch):
        # Not just NoProviderAvailableError — ANY unexpected exception from
        # the provider layer should degrade rather than crash the turn.
        class Boom(LLMProvider):
            name = "boom"

            def is_available(self):
                return True

            async def generate(self, *a, **k):
                raise RuntimeError("network exploded")

        monkeypatch.setattr(conversation, "get_provider", lambda tier: Boom())

        result = await conversation.conversation_node(_base_state())
        assert result["agent_response"]  # did not raise
