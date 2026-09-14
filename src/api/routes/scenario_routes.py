"""Scenario routes: list available scenarios."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.scenarios.loader import list_scenarios

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])


@router.get("")
def scenarios(
    language: str | None = None, _user_id: str = Depends(get_current_user)
) -> dict[str, list[dict[str, Any]]]:
    """List available scenarios, optionally filtered by language code."""
    items = [
        {
            "id": s.id,
            "title": s.title,
            "language": s.language,
            "cefr_min": s.cefr_min,
            "cefr_max": s.cefr_max,
            "location": s.location,
        }
        for s in list_scenarios(language)
    ]
    return {"scenarios": items}
