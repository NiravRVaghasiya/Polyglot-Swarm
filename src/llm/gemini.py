"""Gemini (Google) LLM provider.

Wraps ``langchain_google_genai.ChatGoogleGenerativeAI`` behind the
:class:`LLMProvider` interface. Gemini Flash is the "fast" tier — low latency
and cheap for high-volume, latency-sensitive calls (grammar/vocabulary checks).

The SDK is imported lazily so this module loads without
``langchain-google-genai`` installed unless the provider is actually used.
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


class GeminiProvider(LLMProvider):
    """Google Gemini provider — the fast (low-latency) tier."""

    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or settings.llm_fast
        self.api_key = api_key if api_key is not None else settings.google_api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _build_client(self, *, temperature: float, max_tokens: int) -> Any:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=self.model,
            google_api_key=self.api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

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
