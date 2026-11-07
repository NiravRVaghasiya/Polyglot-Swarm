"""Claude (Anthropic) LLM provider.

Wraps ``langchain_anthropic.ChatAnthropic`` behind the :class:`LLMProvider`
interface. The SDK is imported lazily so importing this module does not require
``langchain-anthropic`` to be installed unless the provider is actually used.
"""

from __future__ import annotations

from typing import Any

from src.config import settings
from src.llm.provider import (
    Completion,
    LLMProvider,
    Message,
    apply_json_mode,
    completion_from_langchain,
    to_langchain_messages,
)


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider — the primary (quality) tier."""

    name = "claude"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or settings.llm_primary
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _build_client(self, *, temperature: float, max_tokens: int) -> Any:
        # Lazy import so the module loads without langchain-anthropic installed.
        from langchain_anthropic import ChatAnthropic

        # ``temperature`` is deliberately not forwarded: current Claude models
        # reject non-default sampling parameters, and API version 2026-10-21
        # rejects them on every model.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "max_tokens": max_tokens,
        }
        return ChatAnthropic(**kwargs)

    async def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        completion = await self.generate_detailed(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
        )
        return completion.text

    async def generate_detailed(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> Completion:
        if json_mode:
            messages = apply_json_mode(messages)

        client = self._build_client(temperature=temperature, max_tokens=max_tokens)
        response = await client.ainvoke(to_langchain_messages(messages))
        return completion_from_langchain(response, messages)
