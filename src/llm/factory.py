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

import logging
from collections.abc import Callable

from src.llm.claude import ClaudeProvider
from src.llm.gemini import GeminiProvider
from src.llm.ollama import OllamaProvider
from src.llm.provider import LLMProvider, Message, Tier

logger = logging.getLogger("polyglot.llm")

# Preferred provider for each routing tier.
TIER_PREFERENCE: dict[Tier, str] = {
    "primary": "claude",
    "fast": "gemini",
    "local": "ollama",
}

# Constructors for every known provider, keyed by name.
_PROVIDER_BUILDERS: dict[str, Callable[[], LLMProvider]] = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


class NoProviderAvailableError(RuntimeError):
    """Raised when no configured provider can serve a request."""


class RoutingProvider(LLMProvider):
    """A provider that routes to an ordered chain of concrete providers.

    On each ``generate`` call it tries providers in ``chain`` order, returning
    the first successful result and logging any failovers. Providers that are
    not available (per :meth:`LLMProvider.is_available`) are skipped up front.
    """

    name = "routing"

    def __init__(self, chain: list[LLMProvider], *, tier: Tier | None = None) -> None:
        self._chain = chain
        self.tier = tier

    @property
    def chain(self) -> list[LLMProvider]:
        return self._chain

    def available_chain(self) -> list[LLMProvider]:
        """The subset of the chain whose providers report availability."""
        return [p for p in self._chain if p.is_available()]

    def is_available(self) -> bool:
        return bool(self.available_chain())

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

        last_error: Exception | None = None
        for index, provider in enumerate(candidates):
            try:
                return await provider.generate(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except Exception as exc:  # noqa: BLE001 - failover is intentional
                last_error = exc
                next_provider = (
                    candidates[index + 1].name
                    if index + 1 < len(candidates)
                    else None
                )
                if next_provider is not None:
                    logger.warning(
                        "LLM provider %r failed (%s); failing over to %r",
                        provider.name,
                        exc,
                        next_provider,
                    )
                else:
                    logger.error(
                        "LLM provider %r failed (%s); no further fallback",
                        provider.name,
                        exc,
                    )

        raise NoProviderAvailableError(
            f"All providers failed for tier={self.tier!r}"
        ) from last_error


def _build_chain(tier: Tier) -> list[LLMProvider]:
    """Build the ordered provider chain for a tier.

    The preferred provider for the tier goes first; the remaining providers
    follow in a stable fallback order (claude → gemini → ollama).
    """
    preferred = TIER_PREFERENCE[tier]
    fallback_order = ["claude", "gemini", "ollama"]
    ordered_names = [preferred] + [n for n in fallback_order if n != preferred]
    return [_PROVIDER_BUILDERS[name]() for name in ordered_names]


def get_provider(tier: Tier = "primary") -> RoutingProvider:
    """Return a routing provider for the requested tier.

    Args:
        tier: One of "primary" (quality/Claude), "fast" (low-latency/Gemini),
            or "local" (privacy/Ollama).

    Returns:
        A :class:`RoutingProvider` that prefers the tier's provider and fails
        over to other available providers.
    """
    return RoutingProvider(_build_chain(tier), tier=tier)
