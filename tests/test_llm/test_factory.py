"""Tests for the provider factory: tier routing and failover."""

from __future__ import annotations

import pytest

from src.llm.factory import (
    TIER_PREFERENCE,
    NoProviderAvailableError,
    RoutingProvider,
    get_provider,
)
from src.llm.provider import LLMProvider, Message
from src.llm.reliability import CircuitBreaker, RetryPolicy


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
    def test_preferred_provider_first(self, tier, real_providers):
        provider = get_provider(tier)
        assert provider.tier == tier
        assert provider.chain[0].name == TIER_PREFERENCE[tier]

    def test_chain_contains_all_three(self, real_providers):
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
        router = RoutingProvider([StubProvider("x", available=False)], tier="primary")
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
    async def test_primary_falls_back_when_no_anthropic_key(
        self, fake_langchain, real_providers, monkeypatch
    ):
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


class TestLocalOnlyMode:
    """Phase 21: local_only excludes hosted providers regardless of keys."""

    def test_excludes_hosted_providers_even_with_keys_configured(self, real_providers, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "local_only", True, raising=False)
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-fake", raising=False)
        monkeypatch.setattr(settings, "google_api_key", "fake", raising=False)
        monkeypatch.setattr(settings, "openai_api_key", "fake", raising=False)

        for tier in ("primary", "fast", "local"):
            chain_names = {p.name for p in get_provider(tier).chain}
            assert chain_names == {"ollama"}

    def test_local_only_false_keeps_the_full_chain(self, real_providers, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "local_only", False, raising=False)
        chain_names = {p.name for p in get_provider("primary").chain}
        assert chain_names == {"claude", "gemini", "ollama"}

    def test_local_tier_chain_is_just_ollama_regardless(self, real_providers, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "local_only", True, raising=False)
        assert [p.name for p in get_provider("local").chain] == ["ollama"]


class FlakyProvider(LLMProvider):
    """Fails its first ``fail_times`` calls, then succeeds — for retry tests."""

    name = "flaky"

    def __init__(self, fail_times: int, *, reply: str = "recovered"):
        self.fail_times = fail_times
        self.reply = reply
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.calls}")
        return self.reply


class TestRetryWithBackoff:
    async def test_retries_same_provider_before_failing_over(self, monkeypatch):
        # No sleeping in tests: patch asyncio.sleep so backoff delays are instant.
        import src.llm.factory as factory_module

        async def instant_sleep(_delay):
            return None

        monkeypatch.setattr(factory_module.asyncio, "sleep", instant_sleep)

        flaky = FlakyProvider(fail_times=2)  # fails twice, succeeds on 3rd call
        never_used = StubProvider("never-used")
        router = RoutingProvider(
            [flaky, never_used],
            tier="primary",
            retry_policy=RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.01),
        )

        result = await router.generate([Message("user", "hi")])

        assert result == "recovered"
        assert flaky.calls == 3  # 1 initial attempt + 2 retries
        assert never_used.calls == 0  # never failed over — retry succeeded first

    async def test_exhausts_retries_then_fails_over(self, monkeypatch):
        import src.llm.factory as factory_module

        async def instant_sleep(_delay):
            return None

        monkeypatch.setattr(factory_module.asyncio, "sleep", instant_sleep)

        always_fails = FlakyProvider(fail_times=999)
        fallback = StubProvider("fallback")
        router = RoutingProvider(
            [always_fails, fallback],
            tier="primary",
            retry_policy=RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.01),
        )

        result = await router.generate([Message("user", "hi")])

        assert result == "fallback-reply"
        assert always_fails.calls == 3  # 1 initial + 2 retries, all failed
        assert fallback.calls == 1

    async def test_zero_retries_preserves_original_immediate_failover(self):
        # Default RetryPolicy() has max_retries=0 -> one attempt, then failover,
        # exactly like the pre-Phase-23 behavior.
        primary = StubProvider("primary", fail=True)
        fallback = StubProvider("fallback")
        router = RoutingProvider([primary, fallback], tier="primary")

        result = await router.generate([Message("user", "hi")])

        assert result == "fallback-reply"
        assert primary.calls == 1
        assert fallback.calls == 1


class TestCircuitBreakerIntegration:
    async def test_open_breaker_excludes_provider_from_available_chain(self):
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=100.0)
        # No injected `now` here: available_chain() calls is_open() without one
        # too, so both must use the same (real) clock for this assertion to be
        # meaningful — the cooldown is generous (100s) so the real elapsed time
        # between these two calls is negligible.
        breaker.record_failure("primary")

        primary = StubProvider("primary")
        fallback = StubProvider("fallback")
        router = RoutingProvider([primary, fallback], tier="primary", circuit_breaker=breaker)

        assert [p.name for p in router.available_chain()] == ["fallback"]
        result = await router.generate([Message("user", "hi")])
        assert result == "fallback-reply"
        assert primary.calls == 0  # circuit open — never even attempted

    async def test_repeated_failures_open_the_breaker_across_calls(self):
        # A fresh RoutingProvider each "turn" (as get_provider does), but the
        # SAME breaker instance persists across calls — this is what lets a
        # dead provider stay skipped after enough failures, instead of paying
        # its failure cost again on every subsequent turn.
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=100.0)
        dead = StubProvider("dead", fail=True)
        fallback = StubProvider("fallback")

        # Turn 1: dead fails, records 1 failure, still closed -> tried again.
        router1 = RoutingProvider([dead, fallback], tier="primary", circuit_breaker=breaker)
        await router1.generate([Message("user", "hi")])
        assert dead.calls == 1

        # Turn 2: dead fails again, hits the threshold -> breaker opens.
        router2 = RoutingProvider([dead, fallback], tier="primary", circuit_breaker=breaker)
        await router2.generate([Message("user", "hi")])
        assert dead.calls == 2

        # Turn 3: breaker is open — dead is skipped entirely, not even called.
        router3 = RoutingProvider([dead, fallback], tier="primary", circuit_breaker=breaker)
        result = await router3.generate([Message("user", "hi")])
        assert result == "fallback-reply"
        assert dead.calls == 2  # unchanged — skipped this turn

    async def test_success_resets_failure_count(self):
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=100.0)
        # One failure, then a success, then one more failure — should NOT open
        # (the success should have cleared the failure count), unlike two
        # consecutive failures which would.
        flaky = StubProvider("flaky")
        router = RoutingProvider([flaky], tier="primary", circuit_breaker=breaker)

        breaker.record_failure("flaky", now=0.0)
        await router.generate([Message("user", "hi")])  # succeeds -> resets count
        breaker.record_failure("flaky", now=0.0)

        assert breaker.allow("flaky", now=0.0) is True  # only 1 consecutive failure


class TestDeterministicMode:
    def test_deterministic_env_routes_to_fake(self, monkeypatch):
        # Deterministic mode collapses every tier to the fake provider.
        monkeypatch.setenv("POLYGLOT_DETERMINISTIC", "1")
        for tier in ("primary", "fast", "local"):
            provider = get_provider(tier)
            assert [p.name for p in provider.chain] == ["fake"]
            assert provider.is_available() is True

    async def test_fake_provider_json_mode_is_parseable(self, monkeypatch):
        import json

        monkeypatch.setenv("POLYGLOT_DETERMINISTIC", "1")
        provider = get_provider("primary")
        raw = await provider.generate([Message("user", "hola")], json_mode=True)
        assert isinstance(json.loads(raw), dict)
