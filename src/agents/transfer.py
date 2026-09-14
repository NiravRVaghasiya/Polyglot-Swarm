"""Cross-Language Transfer Agent — exploits similarities across the learner's
target languages.

For words the learner just encountered, it suggests cognates in their OTHER
active languages (e.g. ES "restaurante" -> IT "ristorante" -> PL "restauracja")
and warns about false friends. This turns prior knowledge into leverage,
especially between closely related languages (ES/IT ~82% lexical similarity).

Runs at end of session (surfaced in the report), not during conversation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render
from src.llm.provider import Message
from src.memory import user_profile
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.transfer")


async def suggest_transfers(
    source_language: str,
    words: list[str],
    other_languages: list[str],
) -> list[dict[str, Any]]:
    """Return cognate/false-friend transfer suggestions for ``words``.

    Args:
        source_language: The language the words are in.
        words: Words to analyze (typically newly learned this session).
        other_languages: The learner's other active languages to map to.

    Returns:
        A list of transfer entries; empty if there is nothing to map.
    """
    if not words or not other_languages:
        return []

    prompt = render(
        "transfer.jinja2",
        source_language=source_language,
        other_languages=other_languages,
        words=words,
    )

    provider = get_provider("fast")
    try:
        response_text = await provider.generate(
            [
                Message("system", "You are a cross-language transfer coach. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.2,
            max_tokens=700,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - transfer is a best-effort extra
        logger.warning("Transfer LLM call failed: %s", exc)
        return []

    return _parse_transfers(response_text)


def _parse_transfers(response_text: str) -> list[dict[str, Any]]:
    """Parse the transfer LLM JSON response, tolerating code fences."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        transfers = data.get("transfers", [])
        result: list[dict[str, Any]] = []
        for t in transfers:
            word = t.get("word")
            if not word:
                continue
            result.append(
                {
                    "word": word,
                    "cognates": t.get("cognates", {}) or {},
                    "false_friends": t.get("false_friends", []) or [],
                }
            )
        return result
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return []


async def transfer_node(state: LearnerState) -> dict[str, Any]:
    """Generate transfer suggestions for the session's new vocabulary.

    Reads the learner's other active languages from their profile, asks for
    cognates/false friends for the new words, and returns them on state under
    ``transfer_suggestions`` for the end-of-session report.
    """
    new_vocab = state.get("new_vocabulary", [])
    words = [v["word"] for v in new_vocab if v.get("word")]
    if not words:
        return {"transfer_suggestions": []}

    source_language = state["language"]
    profile = user_profile.load_profile(state["user_id"])
    other_languages = [
        lang for lang in profile.target_languages if lang != source_language
    ]

    suggestions = await suggest_transfers(source_language, words, other_languages)
    return {"transfer_suggestions": suggestions}
