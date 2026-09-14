"""Cultural Context Agent — teaches register, pragmatics, and cultural norms.

This agent runs silently during conversation (like Grammar and Vocabulary): it
analyzes the learner's message for cultural/pragmatic issues — formality
(tú/usted, ty/Pan, tu/Lei), idioms, and customs — collects notes on state, and
persists them to the ChromaDB ``cultural_notes`` collection for later recall.
It never interrupts the dialogue; notes surface in the end-of-session report.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render
from src.llm.provider import Message
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.cultural")


async def cultural_node(state: LearnerState) -> dict[str, Any]:
    """Detect cultural/pragmatic issues in the learner's latest input.

    Runs silently. Notes are appended to state and persisted to the vector
    store. Returns a state update with the accumulated cultural notes.
    """
    user_input = state.get("last_user_input", "")
    existing = state.get("cultural_notes", [])

    if not user_input or len(user_input.strip()) < 3:
        return {"cultural_notes": existing}

    scenario = state.get("current_scenario", {}) or {}
    persona = scenario.get("persona", {}) or {}

    prompt = render(
        "cultural.jinja2",
        language=state["language"],
        context=scenario.get("context", "casual conversation"),
        persona_role=persona.get("role", "a local"),
        location=scenario.get("location", "a city"),
        cefr_level=state.get("cefr_level", "A2"),
        user_text=user_input,
    )

    provider = get_provider("fast")
    response_text = await provider.generate(
        [
            Message("system", "You are a cultural language coach. Respond only in JSON."),
            Message("user", prompt),
        ],
        temperature=0.2,
        max_tokens=500,
        json_mode=True,
    )

    notes = _parse_cultural_response(response_text)
    if not notes:
        return {"cultural_notes": existing}

    _persist_notes(state, notes)

    note_texts = [n["note"] for n in notes]
    return {"cultural_notes": existing + note_texts}


def _parse_cultural_response(response_text: str) -> list[dict[str, str]]:
    """Parse the LLM JSON response into a list of cultural note dicts."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        data = json.loads(text)
        notes = data.get("notes", [])
        return [
            {
                "note": n.get("note", ""),
                "category": n.get("category", "info"),
                "severity": n.get("severity", "info"),
            }
            for n in notes
            if n.get("note")
        ]
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return []


def _persist_notes(state: LearnerState, notes: list[dict[str, str]]) -> None:
    """Persist cultural notes to the ChromaDB ``cultural_notes`` collection.

    Best-effort: a vector-store failure must never break the conversation, so
    errors are logged and swallowed.
    """
    try:
        from src.memory.vector_store import get_vector_store

        store = get_vector_store()
        language = state["language"]
        user_id = state.get("user_id", "unknown")
        store.add(
            "cultural_notes",
            ids=[f"{state['session_id']}-{uuid.uuid4().hex[:8]}" for _ in notes],
            documents=[n["note"] for n in notes],
            metadatas=[
                {
                    "language": language,
                    "user_id": user_id,
                    "category": n["category"],
                    "severity": n["severity"],
                }
                for n in notes
            ],
        )
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        logger.warning("Failed to persist cultural notes: %s", exc)
