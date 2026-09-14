"""Tests for the provider factory: tier routing and failover."""

from __future__ import annotations

import pytest

from src.llm.provider import LLMProvider, Message
from src.llm.factory import (
    NoProviderAvailableError,
    RoutingProvider,
    TIER_PREFERENCE,
    get_provider,
)


class StubProvider(LLMProvider):
    """A controllable provider for exercising the routing logic."""

    def __init__(self, name, *, available=True, fail=False, reply=None):
        self.name = name
        self._available = available
        self._fail = fail
        self._reply = reply if reply is not None else f"{name}-reply"
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls += 1
        if self._fail:
            raise RuntimeError(f"{self.name} boom")
        return self._reply


class TestGetProviderChain:
    @pytest.mark.parametrize("tier", ["primary", "fast", "local"])
    def test_preferred_provider_first(self, tier):
        provider = get_provider(tier)
        assert provider.tier == tier
        assert provider.chain[0].name == TIER_PREFERENCE[tier]

    def test_chain_contains_all_three(self):
        names = {p.name for p in get_provider("primary").chain}
        assert names == {"claude", "gemini", "ollama"}


class TestRoutingBehavior:
    async def test_uses_first_available(self):
        a = StubProvider("a")
        b = StubProvider("b")
        router = RoutingProvider([a, b], tier="primary")

        result = await router.generate([Message("user", "hi")])

        assert result == "a-reply"
        assert a.calls == 1
        assert b.calls == 0

    async def test_skips_unavailable_provider(self):
        primary = StubProvider("primary", available=False)
        fallback = StubProvider("fallback")
        router = RoutingProvider([primary, fallback], tier="primary")

        result = await router.generate([Message("user", "hi")])

        assert result == "fallback-reply"
        assert primary.calls == 0  # never invoked — filtered out
        assert fallback.calls == 1

    async def test_fails_over_on_error(self):
        primary = StubProvider("primary", fail=True)
        fallback = StubProvider("fallback")
        router = RoutingProvider([primary, fallback], tier="primary")

        result = await router.generate([Message("user", "hi")])

        assert result == "fallback-reply"
        assert primary.calls == 1  # tried, then failed over
        assert fallback.calls == 1

    async def test_raises_when_none_available(self):
        router = RoutingProvider(
            [StubProvider("x", available=False)], tier="primary"
        )
        assert router.is_available() is False
        with pytest.raises(NoProviderAvailableError):
            await router.generate([Message("user", "hi")])

    async def test_raises_when_all_fail(self):
        router = RoutingProvider(
            [StubProvider("x", fail=True), StubProvider("y", fail=True)],
            tier="fast",
        )
        with pytest.raises(NoProviderAvailableError):
            await router.generate([Message("user", "hi")])

    async def test_passes_params_through(self):
        captured = {}

        class Capturing(StubProvider):
            async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
                captured["temperature"] = temperature
                captured["max_tokens"] = max_tokens
                captured["json_mode"] = json_mode
                return "ok"

        router = RoutingProvider([Capturing("c")], tier="primary")
        await router.generate(
            [Message("user", "hi")], temperature=0.1, max_tokens=42, json_mode=True
        )
        assert captured == {"temperature": 0.1, "max_tokens": 42, "json_mode": True}


class TestGetProviderAvailabilityWithKeys:
    async def test_primary_falls_back_when_no_anthropic_key(self, fake_langchain, monkeypatch):
        # No Anthropic key, but a Google key present → primary tier should
        # skip Claude and route to Gemini.
        from src.config import settings

        monkeypatch.setattr(settings, "anthropic_api_key", "", raising=False)
        monkeypatch.setattr(settings, "google_api_key", "AIza-test", raising=False)
        monkeypatch.setattr(settings, "ollama_base_url", "", raising=False)

        provider = get_provider("primary")
        available = provider.available_chain()

        assert [p.name for p in available] == ["gemini"]
        result = await provider.generate([Message("user", "hi")])
        assert result == "canned reply"
