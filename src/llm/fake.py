"""Deterministic fake LLM provider for tests, benchmarks, and offline demos.

Activated by :func:`is_deterministic` (``POLYGLOT_DETERMINISTIC=1``). It never
touches the network and returns stable, reproducible output derived only from
the input messages, so:

- the test suite runs without API keys and without flakiness,
- benchmarks measure the surrounding machinery, not model variance,
- a contributor can exercise the full loop fully offline.

When ``json_mode`` is requested it emits syntactically valid JSON so callers
that parse structured output keep working. The reply is otherwise a short,
deterministic echo that is obviously synthetic (prefixed ``[fake]``).
"""

from __future__ import annotations

import hashlib
import json
import os

from src.llm.provider import LLMProvider, Message

#: Environment flag that turns on deterministic mode across the app.
DETERMINISTIC_ENV = "POLYGLOT_DETERMINISTIC"


def is_deterministic() -> bool:
    """Whether deterministic mode is active (``POLYGLOT_DETERMINISTIC`` truthy)."""
    return os.getenv(DETERMINISTIC_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _digest(messages: list[Message]) -> str:
    """A short stable hash of the conversation, for reproducible variety."""
    joined = "\n".join(f"{m.role}:{m.content}" for m in messages)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]


class FakeProvider(LLMProvider):
    """A provider that returns deterministic output without any network call."""

    name = "fake"

    def is_available(self) -> bool:
        return True

    def health(self) -> dict[str, object]:
        return {"provider": self.name, "available": True, "deterministic": True}

    async def generate(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"),
            "",
        )
        digest = _digest(messages)
        if json_mode:
            # Return valid, minimal JSON. Callers that expect a specific schema
            # should override this provider with a purpose-built fake in their
            # own test; this default just guarantees parseable structured output.
            return json.dumps(
                {"ok": True, "echo": last_user[:120], "digest": digest},
                ensure_ascii=False,
            )
        return f"[fake:{digest}] {last_user[:200]}".strip()
