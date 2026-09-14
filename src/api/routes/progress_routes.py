"""Progress routes: overview, vocabulary growth, weaknesses."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.memory import progress

router = APIRouter(prefix="/api/v1/progress", tags=["progress"])


@router.get("/overview")
def overview(
    language: str | None = None, user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    """Return the combined progress overview (streak, words, CEFR, weaknesses)."""
    return progress.progress_overview(user_id, language)


@router.get("/vocabulary")
def vocabulary(
    language: str | None = None,
    days: int = 30,
    user_id: str = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """Return the vocabulary growth series."""
    return {"growth": progress.vocabulary_growth(user_id, language, days=days)}


@router.get("/weaknesses")
def weaknesses(
    language: str | None = None,
    limit: int = 5,
    user_id: str = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """Return the learner's top grammar weaknesses."""
    return {"weaknesses": progress.top_weaknesses(user_id, language, limit=limit)}
