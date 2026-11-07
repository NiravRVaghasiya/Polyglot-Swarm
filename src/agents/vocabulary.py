"""Vocabulary Agent — tracks words the learner knows and encounters.

This agent:
- Identifies new words in conversation (user + agent responses)
- Checks against user's known vocabulary database
- Logs new words with context sentences
- Feeds new items into the FSRS scheduling system
"""

import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.orchestrator.state import LearnerState, VocabularyItem

logger = logging.getLogger("polyglot.vocabulary")


#: Generation parameters of the production vocabulary call (shared with the
#: real-model evaluation runner).
VOCABULARY_TEMPERATURE = 0.0
VOCABULARY_MAX_TOKENS = 500
VOCABULARY_SYSTEM_MESSAGE = "You extract vocabulary. Respond only in JSON."


def build_vocabulary_messages(
    language: str,
    *,
    cefr_level: str,
    user_text: str,
    agent_text: str,
    prompt_version: int | None = None,
) -> list[Message]:
    """The exact messages the vocabulary agent sends for one exchange."""
    prompt = str(
        render_prompt(
            "vocabulary",
            version=prompt_version,
            language=language,
            cefr_level=cefr_level,
            user_text=user_text,
            agent_text=agent_text,
        )
    )
    return [Message("system", VOCABULARY_SYSTEM_MESSAGE), Message("user", prompt)]


async def vocabulary_node(state: LearnerState) -> dict[str, Any]:
    """Extract new vocabulary from the latest conversation turn.

    Args:
        state: Current LearnerState.

    Returns:
        State update with new vocabulary items.
    """
    user_input = state.get("last_user_input", "")
    agent_response = state.get("agent_response", "")

    if not user_input and not agent_response:
        return {"new_vocabulary": []}

    messages = build_vocabulary_messages(
        state["language"],  # User provides full language name
        cefr_level=state.get("cefr_level", "A2"),
        user_text=user_input,
        agent_text=agent_response,
    )

    # Use fast LLM tier for vocabulary extraction (latency-sensitive), with failover.
    # Best-effort like the other analysis agents: a total provider outage
    # means no new words this turn, not a crashed session.
    provider = get_provider("fast")
    try:
        response_text = await provider.generate(
            messages,
            temperature=VOCABULARY_TEMPERATURE,
            max_tokens=VOCABULARY_MAX_TOKENS,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - analysis must never break the turn
        logger.warning("Vocabulary extraction skipped, no LLM provider answered: %s", exc)
        return {"new_vocabulary": state.get("new_vocabulary", [])}

    words = _parse_vocabulary_response(response_text)

    return {"new_vocabulary": state.get("new_vocabulary", []) + words}


def _parse_vocabulary_response(response_text: str) -> list[VocabularyItem]:
    """Parse LLM JSON response into VocabularyItem objects."""
    import json

    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        data = json.loads(text)
        # A model may answer with a bare list or with non-object items; the
        # contract is {"words": [{...}]}, so anything else yields no words
        # rather than an AttributeError that would break the turn.
        if not isinstance(data, dict):
            return []
        words = data.get("words", [])
        if not isinstance(words, list):
            return []

        return [
            VocabularyItem(
                word=w["word"],
                translation=w.get("translation", ""),
                pos=w.get("pos", "unknown"),
                context_sentence=w.get("context_sentence", ""),
                is_new=True,
            )
            for w in words
            if isinstance(w, dict) and w.get("word")
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
