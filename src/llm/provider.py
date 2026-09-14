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
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]

Tier = Literal["primary", "fast", "local"]


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
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)
