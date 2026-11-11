"""Drill generation — targeted practice from the learner's weaknesses + due items.

Pulls the learner's top grammar weaknesses (from the error taxonomy) and the
vocabulary currently due for review (FSRS/next_review), then asks the LLM to
generate short contextual exercises. Following the LECTOR insight, grammar
drills for confusable pairs (e.g. ser vs estar) deliberately include the
confusable form so the learner builds the distinction.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.llm.schemas import strip_code_fences
from src.memory import progress, vocabulary_db

logger = logging.getLogger("polyglot.drills")


async def generate_drills(
    user_id: str,
    language: str,
    *,
    cefr_level: str = "A2",
    max_items: int = 6,
) -> list[dict[str, Any]]:
    """Generate targeted drills for a learner's weaknesses and due vocabulary.

    Returns a list of drill dicts. Empty if the learner has no weaknesses and
    nothing due, or if the LLM call fails.
    """
    weaknesses = [w["error_type"] for w in progress.top_weaknesses(user_id, language)]
    due_words = [item["word"] for item in vocabulary_db.get_due(user_id, language, limit=10)]

    if not weaknesses and not due_words:
        return []

    prompt = str(
        render_prompt(
            "drills",
            language=language,
            cefr_level=cefr_level,
            weaknesses=weaknesses,
            due_words=due_words,
            max_items=max_items,
        )
    )

    provider = get_provider("fast")
    try:
        response_text = await provider.generate(
            [
                Message("system", "You generate targeted language drills. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.4,
            max_tokens=800,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - drills are a best-effort extra
        logger.warning("Drill generation LLM call failed: %s", exc)
        return []

    return _parse_drills(response_text)


def _parse_drills(response_text: str) -> list[dict[str, Any]]:
    """Parse the drills LLM JSON response, tolerating code fences."""
    try:
        data = json.loads(strip_code_fences(response_text))
        drills = data.get("drills", [])
        result: list[dict[str, Any]] = []
        for d in drills:
            if not d.get("prompt"):
                continue
            result.append(
                {
                    "type": d.get("type", "vocab"),
                    "target": d.get("target", ""),
                    "prompt": d["prompt"],
                    "answer": d.get("answer", ""),
                    "confusable": d.get("confusable", ""),
                }
            )
        return result
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return []
