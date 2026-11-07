"""Review routes: due items and review submission (FSRS-backed store)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_current_user
from src.api.schemas import ReviewSubmitRequest
from src.memory import vocabulary_db

router = APIRouter(prefix="/api/v1/review", tags=["review"])


@router.get("/due")
def due(
    language: str | None = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """Return vocabulary items due for review for the authenticated user."""
    items = vocabulary_db.get_due(user_id, language, limit=limit)
    return {"due": items}


@router.post("/submit")
def submit(
    req: ReviewSubmitRequest,
    language: str = "Spanish",
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Grade a review for a word: FSRS scheduling, evidence and learner model.

    This goes through :func:`src.agents.review.grade_review`, the same path as
    in-app reviews. Before ADR-0033 it only bumped a counter, so a word
    reviewed through the API was never rescheduled and stayed due.
    """
    from src.agents.review import grade_review

    rating = req.rating if req.rating is not None else (3 if req.correct else 1)
    if (rating >= 3) != req.correct:
        raise HTTPException(
            status_code=422, detail="rating and correct disagree (ratings 3-4 mean correct)"
        )
    result = grade_review(user_id, language, req.word, rating=rating, mode=req.mode)
    return {
        "status": "recorded",
        "correct": result["correct"],
        "next_review": result["next_review"],
        "event_id": result["event_id"],
    }
