"""Contextual review — retrieval practice that measures actual recall.

Phase 8 keeps the WHAT/WHEN split explicit: the curriculum planner chooses
*what* to review and FSRS (in :mod:`src.agents.srs`) decides *when* an item is
due. This module fills two gaps the plan calls out:

1. **Contextual review generation** — instead of a flat "what does X mean?",
   embed the due item in a short scenario-compatible retrieval prompt, so the
   learner recalls the word *in use*. Falls back to a plain prompt if the LLM
   is unavailable, so review always works offline.

2. **Recall measurement** — grading a review runs FSRS, persists the outcome to
   the vocabulary store, updates the recognition mastery dimension, and emits a
   ``REVIEW_RESULT`` evidence event. That means the learner model is updated
   from *demonstrated recall*, not from scheduler assumptions — the plan's
   "measure actual recall" requirement.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from src.agents.srs import process_review_response
from src.evidence.events import EventType, LearningEvent
from src.evidence.provenance import Provenance
from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.memory import vocabulary_db

logger = logging.getLogger("polyglot.review")


def _fallback_prompt(item: dict[str, Any]) -> str:
    """The plain, offline-safe review cue (mirrors the legacy format)."""
    return (
        "📝 Review: use this word in a sentence.\n"
        f"Word: {item.get('word', '?')}\n"
        f"Context: {item.get('context') or (item.get('contexts') or [''])[0]}"
    )


async def generate_contextual_review(
    item: dict[str, Any],
    language: str,
    *,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a contextual retrieval cue for a due item.

    Returns ``{"cue": str, "expected": str, "word": str}``. Degrades to a plain
    fallback cue on any LLM error, so review never blocks.
    """
    word = item.get("word", "")
    contexts = item.get("contexts") or []
    context = item.get("context") or (contexts[0] if contexts else "")
    scenario_hint = ""
    if scenario and scenario.get("title"):
        scenario_hint = f"Setting: {scenario['title']} ({scenario.get('location', '')})."

    prompt = str(
        render_prompt(
            "review",
            language=language,
            word=word,
            translation=item.get("translation", ""),
            context=context,
            scenario_hint=scenario_hint,
        )
    )

    try:
        provider = get_provider("fast")
        from pydantic import BaseModel

        from src.llm.schemas import parse_structured

        class _Cue(BaseModel):
            cue: str = ""
            expected: str = ""

        raw = await provider.generate(
            [
                Message("system", "You create retrieval-practice cues. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.4,
            max_tokens=200,
            json_mode=True,
        )
        parsed = parse_structured(raw, _Cue)
        if parsed and parsed.cue:
            return {"cue": parsed.cue, "expected": parsed.expected or word, "word": word}
    except Exception as exc:  # noqa: BLE001 - review must never break
        logger.warning("Contextual review generation failed: %s", exc)

    return {"cue": _fallback_prompt(item), "expected": word, "word": word}


def grade_review(
    user_id: str,
    language: str,
    word: str,
    *,
    rating: int,
    card_state: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Grade a review: run FSRS, persist, update mastery, and emit evidence.

    ``rating`` is the FSRS 1-4 scale (1=Again, 2=Hard, 3=Good, 4=Easy). A rating
    of 3+ counts as successful recall.

    Returns the FSRS result (``card_state``, ``next_review``, ``review_log``)
    plus the emitted evidence ``event_id``.
    """
    # WHEN: FSRS computes the next interval deterministically.
    if card_state is None:
        rows = vocabulary_db.get_all_for_user(user_id, language)
        match = next((r for r in rows if r["word"] == word), None)
        card_state = (match or {}).get("card_state")
    if not card_state:
        # No prior card — schedule a fresh one so grading still works.
        from src.agents.srs import schedule_new_items

        card_state = schedule_new_items([{"word": word}])[0]["card_state"]

    result = process_review_response(card_state, rating)
    correct = rating >= 3

    # Belief: persist the outcome + update the recognition dimension.
    vocabulary_db.record_review_outcome(
        user_id,
        language,
        word,
        correct=correct,
        card_state=result["card_state"],
        next_review=result["next_review"],
    )
    vocabulary_db.record_dimension(user_id, language, word, "recognition", success=correct)

    # Evidence: a graded review is strong, demonstrated recall evidence.
    event = LearningEvent.create(
        EventType.REVIEW_RESULT,
        user_id,
        language,
        provenance=Provenance(source="review-v1", session_id=session_id),
        item_id=word,
        observed=word,
        assessment="correct" if correct else "incorrect",
        confidence=0.95,
        payload={"rating": rating},
    )
    from src.evidence import store

    store.record_events([event])

    # Learner model: update skill belief from this recall event immediately.
    from src.learner import get_knowledge_model

    get_knowledge_model().update_from_events(user_id, language, [event.model_dump()])

    return {
        "card_state": result["card_state"],
        "next_review": result["next_review"],
        "review_log": result["review_log"],
        "correct": correct,
        "event_id": event.event_id,
        "graded_at": datetime.now(UTC).isoformat(),
    }
