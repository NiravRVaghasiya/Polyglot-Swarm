"""Provider factory with tiered routing and failover.

Agents ask for a *tier* ("primary", "fast", "local") rather than a concrete
vendor. The factory builds a :class:`RoutingProvider` that:

1. Prefers the provider mapped to the requested tier.
2. Falls back, in a defined order, to any other *available* provider if the
   preferred one is unavailable (missing key) or raises at call time.

This gives intelligent failover — e.g. if Claude is down, a "primary" request
transparently degrades to Gemini, then to a local Ollama model.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, TypeVar

from src.config import settings
from src.llm import telemetry
from src.llm.claude import ClaudeProvider
from src.llm.fake import FakeProvider, is_deterministic
from src.llm.gemini import GeminiProvider
from src.llm.ollama import OllamaProvider
from src.llm.openai import OpenAIProvider
from src.llm.provider import LLMProvider, Message, Tier
from src.llm.reliability import CircuitBreaker, RetryPolicy, default_circuit_breaker
from src.llm.router import resolve_tier

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger("polyglot.llm")

_ModelT = TypeVar("_ModelT", bound="BaseModel")

# Preferred provider for each capability tier. Task-oriented tier aliases
# (critical_reasoning, fast_extraction, ...) are resolved to one of these by
# src.llm.router.resolve_tier before a chain is built.
TIER_PREFERENCE: dict[str, str] = {
    "primary": "claude",
    "fast": "gemini",
    "local": "ollama",
}

# Constructors for every known provider, keyed by name.
_PROVIDER_BUILDERS: dict[str, Callable[[], LLMProvider]] = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


class NoProviderAvailableError(RuntimeError):
    """Raised when no configured provider can serve a request."""


class _CallFailed:
    """Sentinel wrapping the exception from an exhausted retry loop.

    A plain sentinel (rather than raising immediately) so the failover loop in
    :meth:`RoutingProvider.generate` can decide what to log/record without an
    exception unwinding through it on every provider in the chain.
    """

    __slots__ = ("error",)

    def __init__(self, error: Exception) -> None:
        self.error = error


class RoutingProvider(LLMProvider):
    """A provider that routes to an ordered chain of concrete providers.

    On each ``generate`` call it tries providers in ``chain`` order, returning
    the first successful result and logging any failovers. Providers that are
    not available (per :meth:`LLMProvider.is_available`) are skipped up front.
    """

    name = "routing"

    def __init__(
        self,
        chain: list[LLMProvider],
        *,
        tier: Tier | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._chain = chain
        self.tier = tier
        # Defaults preserve pre-Phase-23 behavior for any caller that builds a
        # RoutingProvider directly (e.g. existing tests): max_retries=0 means
        # one attempt per provider then immediate failover, and a breaker with
        # no recorded failures never blocks anything.
        self.retry_policy = retry_policy or RetryPolicy()
        self.circuit_breaker = circuit_breaker or default_circuit_breaker

    @property
    def chain(self) -> list[LLMProvider]:
        return self._chain

    def available_chain(self) -> list[LLMProvider]:
        """The subset of the chain whose providers report availability.

        Also excludes providers whose circuit breaker is currently open (i.e.
        recently failed repeatedly and is in its cooldown window) — an
        available-but-known-bad provider is treated the same as an
        unconfigured one for the purposes of building the failover order.
        """
        return [
            p for p in self._chain if p.is_available() and not self.circuit_breaker.is_open(p.name)
        ]

    def is_available(self) -> bool:
        return bool(self.available_chain())

    def health(self) -> dict[str, object]:
        """Aggregate health of the routing chain (no network calls)."""
        return {
            "provider": self.name,
            "tier": self.tier,
            "available": self.is_available(),
            "chain": [p.health() for p in self._chain],
        }

    async def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        candidates = self.available_chain()
        if not candidates:
            raise NoProviderAvailableError(
                f"No available LLM provider for tier={self.tier!r}. "
                "Check API keys / Ollama base URL in your environment."
            )

        input_tokens = candidates[0].count_tokens(messages)
        last_error: Exception | None = None
        for index, provider in enumerate(candidates):
            result = await self._call_with_retry(
                provider,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                input_tokens=input_tokens,
            )
            if isinstance(result, _CallFailed):
                last_error = result.error
                self.circuit_breaker.record_failure(provider.name)
                next_provider = candidates[index + 1].name if index + 1 < len(candidates) else None
                if next_provider is not None:
                    logger.warning(
                        "LLM provider %r failed after retries (%s); failing over to %r",
                        provider.name,
                        result.error,
                        next_provider,
                    )
                else:
                    logger.error(
                        "LLM provider %r failed after retries (%s); no further fallback",
                        provider.name,
                        result.error,
                    )
                continue
            self.circuit_breaker.record_success(provider.name)
            return result

        raise NoProviderAvailableError(
            f"All providers failed for tier={self.tier!r}"
        ) from last_error

    async def _call_with_retry(
        self,
        provider: LLMProvider,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        input_tokens: int,
    ) -> str | _CallFailed:
        """Call ``provider`` with bounded retry-with-backoff, recording telemetry.

        Retries the SAME provider up to ``retry_policy.max_retries`` times
        (with exponential backoff between attempts) before giving up on it —
        this is deliberately separate from failover, which moves to the next
        provider in the chain. A transient blip (a dropped connection, a rate
        limit that clears in a second) is worth retrying in place; a provider
        that is genuinely down is not worth retrying past the bound, which is
        why failover still happens after retries are exhausted.
        """
        attempt = 0
        while True:
            with telemetry.Timer() as timer:
                try:
                    result = await provider.generate(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                    )
                except Exception as exc:  # noqa: BLE001 - retry/failover is intentional
                    self._record(provider, timer, input_tokens, 0, success=False, error=str(exc))
                    if attempt >= self.retry_policy.max_retries:
                        return _CallFailed(exc)
                    delay = self.retry_policy.delay_for(attempt)
                    logger.warning(
                        "LLM provider %r attempt %d failed (%s); retrying in %.2fs",
                        provider.name,
                        attempt + 1,
                        exc,
                        delay,
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
                    attempt += 1
                    continue
            output_tokens = max(1, len(result) // 4)
            self._record(provider, timer, input_tokens, output_tokens, success=True)
            return result

    def _record(
        self,
        provider: LLMProvider,
        timer: telemetry.Timer,
        input_tokens: int,
        output_tokens: int,
        *,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Emit a telemetry record for one provider attempt (never raises)."""
        from src.observability.context import current_interaction

        model = getattr(provider, "model", None)
        telemetry.record(
            telemetry.ModelRun(
                provider=provider.name,
                tier=self.tier,
                model=model,
                latency_ms=timer.elapsed_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=telemetry.estimate_cost(model, input_tokens, output_tokens),
                success=success,
                error=error,
                interaction_id=current_interaction(),
            )
        )

    async def generate_structured(
        self,
        messages: list[Message],
        schema: type[_ModelT],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> _ModelT | None:
        """Structured generation over the routing chain (with failover)."""
        from src.llm.schemas import parse_structured

        raw = await self.generate(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=True
        )
        return parse_structured(raw, schema)

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> AsyncIterator[str]:
        """Stream from the first available provider in the chain."""
        candidates = self.available_chain()
        if not candidates:
            raise NoProviderAvailableError(f"No available LLM provider for tier={self.tier!r}.")
        async for chunk in candidates[0].stream(
            messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield chunk

    def count_tokens(self, messages: list[Message]) -> int:
        chain = self.available_chain() or self._chain
        return chain[0].count_tokens(messages) if chain else 0


#: Names of hosted (non-local) providers. Used by local-only mode (Phase 21)
#: to exclude them from the chain regardless of configured API keys.
_HOSTED_PROVIDERS = frozenset({"claude", "gemini", "openai"})


def _build_chain(tier: Tier) -> list[LLMProvider]:
    """Build the ordered provider chain for a tier.

    Task-oriented tier aliases are resolved to a capability tier first. The
    preferred provider for that tier goes first; the remaining providers follow
    in a stable fallback order (claude → gemini → openai → ollama).

    In local-only mode (Phase 21, ``settings.local_only``), every hosted
    provider is excluded from the chain regardless of which API keys are
    configured — this is what makes "no learning data leaves this machine" an
    enforced guarantee rather than a suggestion. Only Ollama remains; if it is
    unavailable too, :meth:`RoutingProvider.generate` raises
    :class:`NoProviderAvailableError` rather than silently falling back to a
    hosted provider.
    """
    capability = resolve_tier(tier)
    preferred = TIER_PREFERENCE[capability]
    # Base fallback order preserves the original claude → gemini → ollama chain.
    # OpenAI joins the chain only when a key is configured, so deployments that
    # never set OPENAI_API_KEY keep the exact three-provider chain.
    fallback_order = ["claude", "gemini", "ollama"]
    if settings.openai_api_key:
        fallback_order.insert(2, "openai")
    ordered_names = [preferred] + [n for n in fallback_order if n != preferred]
    if settings.local_only:
        ordered_names = [n for n in ordered_names if n not in _HOSTED_PROVIDERS]
    return [_PROVIDER_BUILDERS[name]() for name in ordered_names]


def get_provider(tier: Tier = "primary") -> RoutingProvider:
    """Return a routing provider for the requested tier.

    In deterministic mode (``POLYGLOT_DETERMINISTIC=1``) every tier resolves to
    a single :class:`~src.llm.fake.FakeProvider`, so tests, benchmarks, and
    offline demos never hit the network and produce reproducible output.

    Args:
        tier: One of "primary" (quality/Claude), "fast" (low-latency/Gemini),
            or "local" (privacy/Ollama).

    Returns:
        A :class:`RoutingProvider` that prefers the tier's provider, retries
        transient failures on the same provider with backoff, trips a circuit
        breaker for a provider that keeps failing, and fails over to the next
        available provider once retries/the breaker rule it out.
    """
    if is_deterministic():
        return RoutingProvider([FakeProvider()], tier=tier)
    retry_policy = RetryPolicy(
        max_retries=settings.llm_max_retries,
        base_delay=settings.llm_retry_base_delay,
        max_delay=settings.llm_retry_max_delay,
    )
    return RoutingProvider(_build_chain(tier), tier=tier, retry_policy=retry_policy)
