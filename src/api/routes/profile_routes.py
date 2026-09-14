"""Profile routes: get and update the learner's profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import ProfileUpdateRequest
from src.memory import user_profile
from src.memory.user_profile import UserProfile

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("", response_model=UserProfile)
def get_profile(user_id: str = Depends(get_current_user)) -> UserProfile:
    """Return the authenticated user's profile."""
    return user_profile.load_profile(user_id)


@router.put("", response_model=UserProfile)
def update_profile(
    req: ProfileUpdateRequest, user_id: str = Depends(get_current_user)
) -> UserProfile:
    """Update the authenticated user's profile with the provided fields."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    return user_profile.update_profile(user_id, **fields)
