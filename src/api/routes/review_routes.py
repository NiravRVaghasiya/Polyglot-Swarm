"""Review routes: due items and review submission (FSRS-backed store)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

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
) -> dict[str, str]:
    """Record the outcome of a review for a word."""
    vocabulary_db.record_review_outcome(user_id, language, req.word, correct=req.correct)
    return {"status": "recorded"}
