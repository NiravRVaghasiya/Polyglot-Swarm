"""User profile store — per-user JSON persistence.

Each learner has a profile stored as ``{profiles_dir}/{user_id}.json`` holding
their native language, target languages, per-language CEFR level, goals,
interests, and preferences. Profiles are local-first and human-readable.

The store is intentionally simple (one JSON file per user) since the MVP is
single-user-per-process; the schema carries ``user_id`` so the same code scales
to multi-user once auth is added in the API phase.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from src.config import settings

# CEFR levels, ordered. Used as the value type for per-language proficiency.
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


class UserProfile(BaseModel):
    """A learner's persistent profile."""

    user_id: str
    native_language: str = "English"
    target_languages: list[str] = Field(default_factory=lambda: ["Spanish"])
    # Per-language CEFR estimate, e.g. {"Spanish": "A2"}.
    cefr_by_language: dict[str, str] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    # Free-form preferences (voice on/off, preferred dialect, etc.).
    preferences: dict[str, object] = Field(default_factory=dict)

    def cefr_for(self, language: str, default: str = "A2") -> str:
        """Return the CEFR level for ``language``, or ``default`` if unknown."""
        return self.cefr_by_language.get(language, default)


def _profiles_dir() -> Path:
    path = Path(settings.profiles_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_path(user_id: str) -> Path:
    return _profiles_dir() / f"{user_id}.json"


def default_profile(user_id: str) -> UserProfile:
    """Build a fresh default profile for a new user."""
    return UserProfile(
        user_id=user_id,
        cefr_by_language={"Spanish": "A2"},
    )


def profile_exists(user_id: str) -> bool:
    """Return whether a profile file exists for ``user_id``."""
    return _profile_path(user_id).exists()


def load_profile(user_id: str) -> UserProfile:
    """Load a user's profile, returning a default if none exists yet.

    Loading a missing profile never raises — it returns a sensible default so
    first-time users get a working session without a separate signup step.
    """
    path = _profile_path(user_id)
    if not path.exists():
        return default_profile(user_id)

    data = json.loads(path.read_text(encoding="utf-8"))
    return UserProfile.model_validate(data)


def save_profile(profile: UserProfile) -> UserProfile:
    """Persist a profile to disk atomically and return it.

    The write goes to a temp file in the same directory, then is atomically
    renamed into place so a crash mid-write cannot corrupt an existing profile.
    """
    directory = _profiles_dir()
    path = _profile_path(profile.user_id)
    payload = profile.model_dump_json(indent=2)

    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        # Clean up the temp file on any failure so we don't leak partial writes.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise

    return profile


def create_profile(user_id: str, **fields: object) -> UserProfile:
    """Create and persist a new profile, overriding defaults with ``fields``."""
    base = default_profile(user_id).model_dump()
    base.update(fields)
    profile = UserProfile.model_validate(base)
    return save_profile(profile)


def update_profile(user_id: str, **fields: object) -> UserProfile:
    """Load, apply ``fields``, and persist a profile. Creates it if missing."""
    profile = load_profile(user_id)
    updated = profile.model_copy(update=fields)
    return save_profile(updated)
