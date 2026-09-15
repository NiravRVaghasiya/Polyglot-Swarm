"""OpenAI (GPT) LLM provider.

Wraps ``langchain_openai.ChatOpenAI`` behind the :class:`LLMProvider`
interface, mirroring the Claude/Gemini adapters. The SDK is imported lazily so
importing this module does not require ``langchain-openai`` to be installed
unless the provider is actually used. Availability is gated on an API key.

OpenAI has no dedicated tier of its own; it participates in the routing chain
as an additional fallback when ``OPENAI_API_KEY`` is configured.
"""

from __future__ import annotations

from typing import Any

from src.config import settings
from src.llm.provider import (
    LLMProvider,
    Message,
    apply_json_mode,
    normalize_content,
    to_langchain_messages,
)

# Default model when none is configured. Kept here (not in Settings) since the
# original three tiers own the three model settings; OpenAI is a fallback.
_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider — an optional fallback in the routing chain."""

    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or _DEFAULT_MODEL
        self.api_key = api_key if api_key is not None else settings.openai_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _build_client(self, *, temperature: float, max_tokens: int) -> Any:
        # Lazy import so the module loads without langchain-openai installed.
        from langchain_openai import ChatOpenAI

        # Built as a mapping (like the Claude adapter) because ``ChatOpenAI``
        # types ``api_key`` as ``SecretStr`` and exposes ``max_tokens`` under
        # the ``max_completion_tokens`` alias; pydantic still accepts the plain
        # string and the field name at runtime, across SDK versions.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return ChatOpenAI(**kwargs)

    async def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        if json_mode:
            messages = apply_json_mode(messages)

        client = self._build_client(temperature=temperature, max_tokens=max_tokens)
        response = await client.ainvoke(to_langchain_messages(messages))
        return normalize_content(response.content)
