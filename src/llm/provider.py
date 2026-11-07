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
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class Completion:
    """A completion plus what the provider reported about producing it.

    Used where the text alone is not enough — the real-model evaluation
    runner records token usage and the model identity the provider *reported*
    (which can differ from the requested alias). ``tokens_estimated`` is True
    when the provider gave no usage and the counts are a heuristic.
    """

    text: str
    input_tokens: int
    output_tokens: int
    tokens_estimated: bool
    #: Model name as reported by the provider response, if any.
    reported_model: str | None = None
    #: Provider response metadata (finish reason, ids, ...), JSON-safe values only.
    metadata: dict[str, Any] = field(default_factory=dict)


def completion_from_langchain(response: Any, messages: list[Message]) -> Completion:
    """Build a :class:`Completion` from a LangChain ``AIMessage``-like response.

    Reads ``usage_metadata`` (LangChain's provider-neutral usage block) when
    present and falls back to the ~4-chars-per-token heuristic, flagged as an
    estimate, when it is not.
    """
    text = normalize_content(getattr(response, "content", ""))
    usage = getattr(response, "usage_metadata", None) or {}
    meta_raw = getattr(response, "response_metadata", None) or {}
    metadata = {
        k: v
        for k, v in dict(meta_raw).items()
        if isinstance(v, (str, int, float, bool)) or v is None
    }
    reported = (
        meta_raw.get("model_name") or meta_raw.get("model") if isinstance(meta_raw, dict) else None
    )
    in_tok = usage.get("input_tokens") if isinstance(usage, dict) else None
    out_tok = usage.get("output_tokens") if isinstance(usage, dict) else None
    if isinstance(in_tok, int) and isinstance(out_tok, int):
        return Completion(text, in_tok, out_tok, False, reported, metadata)
    est_in = max(1, sum(len(m.content) for m in messages) // 4)
    est_out = max(1, len(text) // 4) if text else 0
    return Completion(text, est_in, est_out, True, reported, metadata)


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

    async def generate_detailed(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> Completion:
        """Like :meth:`generate`, but also return token usage and metadata.

        The default wraps :meth:`generate` and estimates tokens (flagged as an
        estimate); SDK-backed providers override it with reported usage.
        """
        text = await self.generate(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
        )
        return Completion(
            text=text,
            input_tokens=self.count_tokens(messages),
            output_tokens=max(1, len(text) // 4) if text else 0,
            tokens_estimated=True,
        )

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
