"""FSRS Spaced Repetition Agent — optimal review scheduling.

Uses the FSRS algorithm (Free Spaced Repetition Scheduler) for state-of-the-art
memory scheduling — 20-40% more efficient than Anki's SM-2.

Targets py-fsrs 6.x: ``Scheduler.review_card(card, rating, review_datetime)``
returns ``(card, review_log)``, and ``Card`` serializes via ``to_dict()`` /
``Card.from_dict()``.

References:
- https://github.com/open-spaced-repetition/py-fsrs
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fsrs import Card, Rating, Scheduler

from src.orchestrator.state import LearnerState

# Default scheduler; parameters can be personalized per-user with enough data.
scheduler = Scheduler()

_RATING_MAP = {
    1: Rating.Again,
    2: Rating.Hard,
    3: Rating.Good,
    4: Rating.Easy,
}


def review_node(state: LearnerState) -> dict[str, Any]:
    """Handle a spaced-repetition review turn.

    Presents the next due item (if any) and removes it from the pending queue.
    """
    pending = state.get("pending_reviews", [])
    if not pending:
        return {"mode": "conversation", "pending_reviews": []}

    current_item = pending[0]
    return {
        "agent_response": _format_review_prompt(current_item, state["language"]),
        "pending_reviews": pending[1:],
    }


def schedule_new_items(vocabulary_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create FSRS cards for freshly learned vocabulary and schedule first review.

    Each new word is reviewed once as ``Good`` (a fresh encounter), producing an
    initial ``next_review`` and serialized card state.
    """
    scheduled: list[dict[str, Any]] = []
    now = datetime.now(UTC)

    for item in vocabulary_items:
        card = Card()
        card, _log = scheduler.review_card(card, Rating.Good, now)
        scheduled.append(
            {
                "word": item["word"],
                "translation": item.get("translation", ""),
                "context": item.get("context_sentence", ""),
                "card_state": card.to_dict(),
                "next_review": card.due.isoformat(),
                "created_at": now.isoformat(),
            }
        )

    return scheduled


def process_review_response(card_state: dict[str, Any], rating: int) -> dict[str, Any]:
    """Process a user's rating (1=Again, 2=Hard, 3=Good, 4=Easy) for a card.

    Returns the updated serialized card state, next review time, and a review log.
    """
    card = Card.from_dict(card_state)  # type: ignore[arg-type]
    fsrs_rating = _RATING_MAP.get(rating, Rating.Good)

    updated_card, review_log = scheduler.review_card(
        card, fsrs_rating, datetime.now(UTC)
    )

    return {
        "card_state": updated_card.to_dict(),
        "next_review": updated_card.due.isoformat(),
        "review_log": {
            "rating": rating,
            "reviewed_at": datetime.now(UTC).isoformat(),
        },
    }


def get_due_items(
    all_items: list[dict[str, Any]], limit: int = 10
) -> list[dict[str, Any]]:
    """Return items whose ``next_review`` is due now, most overdue first."""
    now = datetime.now(UTC)
    due = [
        item
        for item in all_items
        if datetime.fromisoformat(item["next_review"]) <= now
    ]
    due.sort(key=lambda x: x["next_review"])
    return due[:limit]


def _format_review_prompt(item: dict[str, Any], language: str) -> str:
    """Format a review item as a user-facing prompt."""
    return (
        "📝 Review time!\n"
        f"Word: {item.get('word', '?')}\n"
        f"Context: {item.get('context', '')}\n"
        "What does it mean? (type your answer)"
    )
