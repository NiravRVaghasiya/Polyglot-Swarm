"""User profile store.

Each learner has a profile holding their native language, target languages,
per-language CEFR level, goals, interests, and preferences. It is stored in
SQLite (:mod:`src.memory.profiles_db`). Older versions also wrote
``{profiles_dir}/{user_id}.json``; such a file is still read when no SQLite
row exists, and removed when the profile is deleted.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.config import settings

#: The band the tutor pitches its language at before anything is known about
#: the learner. It is an *instructional* default for prompts only: it is never
#: stored in a profile, logged as an estimate, or shown as the learner's level
#: (ADR-0031). The learner's assessed level comes from the evidence-backed
#: CEFR profile, which is ``None`` until there is enough evidence.
DEFAULT_WORKING_LEVEL = "A2"


class UserProfile(BaseModel):
    """A learner's persistent profile."""

    user_id: str
    native_language: str = "English"
    target_languages: list[str] = Field(default_factory=lambda: ["Spanish"])
    # Per-language *working level* the tutor pitches at, e.g. {"Spanish": "A2"}:
    # set by onboarding (self-report) or the session heuristic, never seeded.
    # It is not the assessed level (see src.assessment.cefr_profile).
    cefr_by_language: dict[str, str] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    # Free-form preferences (voice on/off, preferred dialect, etc.).
    preferences: dict[str, object] = Field(default_factory=dict)

    def cefr_for(self, language: str, default: str = DEFAULT_WORKING_LEVEL) -> str:
        """Return the tutor's working level for ``language`` (``default`` if unset).

        For pitching prompts only; use :meth:`has_working_level` to tell a
        recorded level from the instructional default.
        """
        return self.cefr_by_language.get(language, default)

    def has_working_level(self, language: str) -> bool:
        """Whether a working level was ever recorded for ``language``."""
        return language in self.cefr_by_language


def _profiles_dir() -> Path:
    path = Path(settings.profiles_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_path(user_id: str) -> Path:
    return _profiles_dir() / f"{user_id}.json"


def default_profile(user_id: str) -> UserProfile:
    """Build a fresh default profile for a new user.

    No CEFR level is seeded: nothing is known about a new learner yet.
    """
    return UserProfile(user_id=user_id)


def profile_exists(user_id: str) -> bool:
    """Return whether a profile exists for ``user_id`` (SQLite or JSON mirror)."""
    from src.memory import profiles_db

    if profiles_db.exists(user_id):
        return True
    return _profile_path(user_id).exists()


def load_profile(user_id: str) -> UserProfile:
    """Load a user's profile, returning a default if none exists yet.

    SQLite is the source of truth (Phase 2): if a row exists it wins. Otherwise
    a JSON file written by an older version is used (and back-filled into
    SQLite).
    Loading a missing profile never raises — it returns a sensible default so
    first-time users get a working session without a separate signup step.
    """
    from src.memory import profiles_db

    stored = profiles_db.get(user_id)
    if stored is not None:
        return UserProfile.model_validate(stored)

    path = _profile_path(user_id)
    if not path.exists():
        return default_profile(user_id)

    data = json.loads(path.read_text(encoding="utf-8"))
    profile = UserProfile.model_validate(data)
    # Back-fill the SQLite source of truth from the legacy JSON mirror.
    try:
        profiles_db.save(profile.model_dump())
    except Exception:  # noqa: BLE001, S110
        pass
    return profile


def save_profile(profile: UserProfile) -> UserProfile:
    """Persist a profile to SQLite (the only store written) and return it."""
    from src.memory import profiles_db

    profiles_db.save(profile.model_dump())
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


def delete_profile(user_id: str) -> None:
    """Delete a user's profile: the SQLite row and any legacy JSON file (Phase 21).

    A no-op (not an error) if either is already absent.
    """
    from src.memory import profiles_db

    profiles_db.delete(user_id)
    path = _profile_path(user_id)
    if path.exists():
        path.unlink()
