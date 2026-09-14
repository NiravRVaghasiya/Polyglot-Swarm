"""Ollama (local) LLM provider.

Wraps ``langchain_community.chat_models.ChatOllama`` behind the
:class:`LLMProvider` interface. This is the "local" / privacy tier — runs a
model such as Llama 3.1 on the user's own machine, so no data leaves the
device. Availability is determined by a configured base URL rather than an
API key.

The SDK is imported lazily so this module loads without
``langchain-community`` installed unless the provider is actually used.
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


def _strip_provider_prefix(model: str) -> str:
    """Normalize a model name like ``ollama/llama3.1:8b`` to ``llama3.1:8b``.

    Settings express the local model as ``ollama/<name>`` for routing clarity,
    but the Ollama client expects the bare model name.
    """
    prefix = "ollama/"
    return model[len(prefix):] if model.startswith(prefix) else model


class OllamaProvider(LLMProvider):
    """Local Ollama provider — the privacy/offline tier."""

    name = "ollama"

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        self.model = _strip_provider_prefix(model or settings.llm_local)
        self.base_url = base_url if base_url is not None else settings.ollama_base_url

    def is_available(self) -> bool:
        # No API key needed; a configured base URL is enough to attempt use.
        return bool(self.base_url)

    def _build_client(self, *, temperature: float, max_tokens: int) -> Any:
        # Prefer the standalone langchain-ollama package; fall back to the
        # (deprecated) langchain-community location for older environments.
        try:
            from langchain_ollama import ChatOllama  # type: ignore[import-not-found]
        except ImportError:
            from langchain_community.chat_models import ChatOllama  # type: ignore[no-redef]

        return ChatOllama(
            model=self.model,
            base_url=self.base_url,
            temperature=temperature,
            num_predict=max_tokens,
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
