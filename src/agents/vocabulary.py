"""Vocabulary Agent — tracks words the learner knows and encounters.

This agent:
- Identifies new words in conversation (user + agent responses)
- Checks against user's known vocabulary database
- Logs new words with context sentences
- Feeds new items into the FSRS scheduling system
"""

from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.orchestrator.state import LearnerState, VocabularyItem


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

    language_name = state["language"]  # User provides full language name

    prompt = str(
        render_prompt(
            "vocabulary",
            language=language_name,
            cefr_level=state.get("cefr_level", "A2"),
            user_text=user_input,
            agent_text=agent_response,
        )
    )

    # Use fast LLM tier for vocabulary extraction (latency-sensitive), with failover.
    provider = get_provider("fast")
    response_text = await provider.generate(
        [
            Message("system", "You extract vocabulary. Respond only in JSON."),
            Message("user", prompt),
        ],
        temperature=0.0,
        max_tokens=500,
        json_mode=True,
    )

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
        words = data.get("words", [])

        return [
            VocabularyItem(
                word=w["word"],
                translation=w.get("translation", ""),
                pos=w.get("pos", "unknown"),
                context_sentence=w.get("context_sentence", ""),
                is_new=True,
            )
            for w in words
            if w.get("word")
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
