"""LLM provider abstraction.

Defines a provider-agnostic interface that every concrete LLM client
(Claude, Gemini, Ollama) implements. Agents depend ONLY on this interface,
never on a concrete SDK.

Design notes:
- Concrete providers import their heavy SDKs lazily (inside methods) so that
  importing this module — and the factory — never requires every provider's
  package to be installed. A deployment that only uses Claude does not need
  the Gemini or Ollama packages present.
- ``generate`` is async so the agents and orchestrator can run providers
  concurrently and integrate cleanly with FastAPI's async stack.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]

# Routing tiers. The original three describe *capability* (primary/fast/local);
# Phase 1 adds task-oriented aliases (see src/llm/router.py) that map onto them
# so callers can route by task without breaking existing tier names.
Tier = Literal[
    "primary",
    "fast",
    "local",
    "critical_reasoning",
    "fast_extraction",
    "cheap_classification",
    "local_private",
]

_ModelT = TypeVar("_ModelT", bound="BaseModel")


@dataclass(frozen=True)
class Message:
    """A normalized chat message, independent of any provider SDK."""

    role: Role
    content: str


class LLMProvider(ABC):
    """Abstract base every concrete LLM provider implements.

    A provider is a thin, stateless adapter over a vendor SDK. It maps the
    normalized :class:`Message` list into the SDK's own message types, invokes
    the model, and returns the plain-text completion.
    """

    #: Human-readable provider name, used for logging/failover diagnostics.
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether this provider is usable (e.g. API key present).

        The factory uses this to skip providers that cannot run so that
        failover only considers viable candidates.
        """
        ...

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        """Generate a completion for ``messages``.

        Args:
            messages: Ordered conversation turns.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            json_mode: When True, steer the model toward valid JSON output.

        Returns:
            The model's completion as plain text.
        """
        ...

    async def generate_structured(
        self,
        messages: list[Message],
        schema: type[_ModelT],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> _ModelT | None:
        """Generate a completion and validate it against a Pydantic ``schema``.

        Default implementation calls :meth:`generate` with ``json_mode=True``
        and parses the result with :func:`src.llm.schemas.parse_structured`,
        returning ``None`` if the output is not valid for the schema. Providers
        with native structured-output support may override for reliability.
        """
        from src.llm.schemas import parse_structured

        raw = await self.generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return parse_structured(raw, schema)

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> AsyncIterator[str]:
        """Yield the completion incrementally.

        The default implementation is non-streaming: it awaits :meth:`generate`
        and yields the whole result once, so every provider supports the
        streaming interface even if the underlying SDK call is not incremental.
        Providers with real token streaming override this.
        """
        text = await self.generate(messages, temperature=temperature, max_tokens=max_tokens)
        yield text

    def count_tokens(self, messages: list[Message]) -> int:
        """Estimate the number of input tokens for ``messages``.

        The default is a cheap, provider-agnostic heuristic (~4 characters per
        token) so telemetry and budget checks work without a tokenizer
        dependency. Providers may override with an exact tokenizer.
        """
        chars = sum(len(m.content) for m in messages)
        return max(1, chars // 4)

    def health(self) -> dict[str, object]:
        """Return a cheap, non-network health snapshot for this provider.

        Reports whether the provider is *configured* (per :meth:`is_available`)
        without making a model call, so it is safe to invoke frequently (e.g.
        from the ``polyglot health`` command or an API readiness probe). A
        provider may override this to perform a real reachability check.
        """
        return {"provider": self.name, "available": self.is_available()}

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{self.__class__.__name__} name={self.name!r}>"


# JSON-steering instruction appended to the system prompt when json_mode is on.
# Kept here so every provider that lacks a native JSON mode behaves the same.
JSON_MODE_INSTRUCTION = (
    "You must respond with valid JSON only. Do not include any prose, "
    "explanations, or markdown fences around the JSON."
)


def apply_json_mode(messages: list[Message]) -> list[Message]:
    """Return a copy of ``messages`` with a JSON-steering system instruction.

    If a system message already exists, the instruction is appended to it;
    otherwise a new system message is prepended. Used by providers that do not
    expose a native structured-output flag.
    """
    instruction = JSON_MODE_INSTRUCTION
    out: list[Message] = []
    injected = False
    for msg in messages:
        if msg.role == "system" and not injected:
            out.append(Message("system", f"{msg.content}\n\n{instruction}"))
            injected = True
        else:
            out.append(msg)
    if not injected:
        out.insert(0, Message("system", instruction))
    return out


def to_langchain_messages(messages: list[Message]) -> list[Any]:
    """Map normalized :class:`Message` objects to LangChain message objects.

    Imported lazily so callers do not require ``langchain-core`` at import time.
    Shared by all providers to keep role mapping consistent.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    mapping = {
        "system": SystemMessage,
        "user": HumanMessage,
        "assistant": AIMessage,
    }
    return [mapping[m.role](content=m.content) for m in messages]


def normalize_content(content: Any) -> str:
    """Normalize a LangChain response ``content`` field to plain text.

    Some providers return a list of content blocks (dicts with a ``text`` key)
    rather than a single string; this flattens either form to ``str``.
    """
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)
