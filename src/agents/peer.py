"""Peer conversation mode — two agents converse for the learner to follow.

Instead of talking *to* the learner, two Conversation personas hold a short
dialogue that the learner listens to and follows, ending with a comprehension
check. This is a listening/immersion exercise (a "peer" or eavesdropping mode)
rather than an interactive one.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message

logger = logging.getLogger("polyglot.peer")


async def generate_peer_dialogue(
    language: str,
    *,
    cefr_level: str = "A2",
    topic: str = "everyday small talk",
    speaker_a: str = "Ana",
    speaker_b: str = "Marco",
    turns: int = 4,
) -> dict[str, Any]:
    """Generate a two-speaker dialogue plus a comprehension question.

    Returns ``{"dialogue": [{"speaker", "text"}], "comprehension": {"question",
    "answer"}}``. Returns empty structures on parse/LLM failure.
    """
    prompt = str(
        render_prompt(
            "peer",
            language=language,
            cefr_level=cefr_level,
            topic=topic,
            speaker_a=speaker_a,
            speaker_b=speaker_b,
            turns=turns,
        )
    )

    provider = get_provider("primary")
    try:
        response_text = await provider.generate(
            [
                Message("system", "You script language-learning dialogues. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.7,
            max_tokens=700,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort feature
        logger.warning("Peer dialogue generation failed: %s", exc)
        return {"dialogue": [], "comprehension": None}

    return _parse_peer_response(response_text)


def _parse_peer_response(response_text: str) -> dict[str, Any]:
    """Parse the peer-dialogue JSON, tolerating code fences."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        dialogue = [
            {"speaker": t.get("speaker", ""), "text": t.get("text", "")}
            for t in data.get("dialogue", [])
            if t.get("text")
        ]
        comprehension = data.get("comprehension")
        if comprehension and not comprehension.get("question"):
            comprehension = None
        return {"dialogue": dialogue, "comprehension": comprehension}
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return {"dialogue": [], "comprehension": None}


def format_peer_dialogue(result: dict[str, Any]) -> str:
    """Render a peer dialogue + comprehension question for display."""
    dialogue = result.get("dialogue", [])
    if not dialogue:
        return "No dialogue available."
    lines = ["🎭 Listen to this conversation:", ""]
    for turn in dialogue:
        lines.append(f"{turn['speaker']}: {turn['text']}")
    comprehension = result.get("comprehension")
    if comprehension:
        lines += ["", f"❓ {comprehension['question']}"]
    return "\n".join(lines)
