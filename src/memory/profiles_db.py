"""SQLite-backed learner profile store (the source of truth).

Phase 2 makes SQLite the source of truth for learner state. Profiles were
previously JSON-only (:mod:`src.memory.user_profile`); this store persists the
same fields to the ``profiles`` table. ``user_profile`` now writes through to
here and reads here first, keeping the JSON file as a human-readable mirror so
existing behavior and tests continue to work.

Kept dependency-light and free of the pydantic model import to avoid cycles:
callers pass/receive plain dicts of the profile fields.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.memory.db import get_connection
from src.memory.schema import init_all

_JSON_FIELDS = ("target_languages", "cefr_by_language", "goals", "interests", "preferences")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    for field in _JSON_FIELDS:
        if field in data and isinstance(data[field], str):
            data[field] = json.loads(data[field])
    # Drop bookkeeping columns not part of the profile model.
    data.pop("created_at", None)
    data.pop("updated_at", None)
    return data


def get(user_id: str) -> dict[str, Any] | None:
    """Return the stored profile dict for ``user_id``, or ``None`` if absent."""
    init_all()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return _row_to_dict(row) if row else None


def save(profile: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a profile from a plain dict of fields. Returns it back."""
    init_all()
    now = _now()
    user_id = profile["user_id"]
    values = {
        "native_language": profile.get("native_language", "English"),
        "target_languages": json.dumps(profile.get("target_languages", [])),
        "cefr_by_language": json.dumps(profile.get("cefr_by_language", {})),
        "goals": json.dumps(profile.get("goals", [])),
        "interests": json.dumps(profile.get("interests", [])),
        "preferences": json.dumps(profile.get("preferences", {})),
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO profiles (user_id, native_language, target_languages,
                                  cefr_by_language, goals, interests, preferences,
                                  created_at, updated_at)
            VALUES (:user_id, :native_language, :target_languages, :cefr_by_language,
                    :goals, :interests, :preferences, :created_at, :updated_at)
            ON CONFLICT(user_id) DO UPDATE SET
                native_language = excluded.native_language,
                target_languages = excluded.target_languages,
                cefr_by_language = excluded.cefr_by_language,
                goals = excluded.goals,
                interests = excluded.interests,
                preferences = excluded.preferences,
                updated_at = excluded.updated_at
            """,
            {"user_id": user_id, **values, "created_at": now, "updated_at": now},
        )
    return profile


def exists(user_id: str) -> bool:
    """Whether a profile row exists for ``user_id``."""
    init_all()
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return row is not None


def delete(user_id: str) -> bool:
    """Delete the profile row for ``user_id`` (Phase 21 data deletion).

    Returns whether a row was actually removed. Callers that also mirror the
    profile to a JSON file (:mod:`src.memory.user_profile`) must delete that
    file separately — this only touches the SQLite row.
    """
    init_all()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
        return cursor.rowcount > 0
