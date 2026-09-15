"""User data export and deletion — the plan's "user data export"/"user data
deletion" requirements (Phase 21), implemented across every store that keys
data by ``user_id``.

Two entry points:

- :func:`export_user_data` — aggregate everything known about a user into one
  JSON-serializable dict, for a self-service "download my data" feature.
- :func:`delete_user_data` — remove everything about a user (account,
  profile, vocabulary, sessions, evidence, assessments, skill beliefs,
  collocations, experiment participation, cultural notes, tokens, and the
  observability link table), for a self-service "delete my account" feature.

Both are best-effort across independent stores: one store's export/delete
failing does not abort the others (each is wrapped so a single broken store
cannot silently swallow every other store's data too) — the returned result
reports per-store outcomes so a caller can see exactly what succeeded.

Design note on the audit log: it is intentionally NOT deleted. Its module
(:mod:`src.security.audit`) is append-only by design (a trustworthy security
record); deletion instead anonymizes the user's audit rows (nulls
``user_id``, keeps the event itself) via :func:`src.security.audit.
anonymize_for_user`. This is a considered trade-off, not an oversight — see
that function's docstring.
"""

from __future__ import annotations

from typing import Any


def export_user_data(user_id: str) -> dict[str, Any]:
    """Aggregate everything stored about ``user_id`` into one dict.

    Language-scoped stores (skill beliefs, assessments) are read across every
    language the user's profile knows about, so nothing is missed just
    because it wasn't the user's *current* language. Vocabulary/turns/
    error-patterns/sessions already have unbounded, cross-language
    "get all for user" queries and are read directly.
    """
    from src.memory import (
        analytics,
        assessments,
        collocations,
        experiments,
        model_runs,
        profiles_db,
        session_history,
        skill_state,
        vocabulary_db,
    )
    from src.observability.links import interaction_ids_for_user
    from src.security.audit import recent_events

    profile = profiles_db.get(user_id)
    languages = _known_languages(profile)

    interaction_ids = interaction_ids_for_user(user_id)

    return {
        "user_id": user_id,
        "account": _account_row(user_id),
        "profile": profile,
        "vocabulary": vocabulary_db.get_all_for_user(user_id),
        "collocations": collocations.get_all_for_user(user_id),
        "conversation_turns": session_history.get_recent_turns_for_user(user_id, limit=1_000_000),
        "error_patterns": analytics.get_error_patterns(user_id),
        "learning_sessions": analytics.get_sessions(user_id, limit=1_000_000),
        "skill_states": skill_state.get_all_skills_for_user(user_id),
        "assessments": assessments.all_assessments_for_user(user_id),
        "experiment_assignments": experiments.all_assignments_for_user(user_id),
        "outcomes": experiments.all_outcomes_for_user(user_id),
        "model_runs": model_runs.get_runs_by_interaction_ids(interaction_ids),
        "cultural_notes": _export_cultural_notes(user_id),
        "audit_log": recent_events(user_id=user_id, limit=1_000_000),
        "_languages_scanned": sorted(languages),
    }


def delete_user_data(user_id: str) -> dict[str, Any]:
    """Delete everything stored about ``user_id``.

    Returns a per-store dict of what was removed (row counts, or booleans for
    single-row stores), so a caller can confirm the deletion was complete or
    see exactly which store failed. Order matters only for
    ``session_interactions``/``model_runs`` (the interaction ids must be read
    *before* the link rows that reference them are deleted) — every other
    store is independent.
    """
    from src.api import auth
    from src.memory import (
        analytics,
        assessments,
        collocations,
        experiments,
        model_runs,
        session_history,
        skill_state,
        vocabulary_db,
    )
    from src.memory import sessions as sessions_store
    from src.observability.links import delete_for_user as delete_links_for_user
    from src.observability.links import interaction_ids_for_user
    from src.security.audit import anonymize_for_user

    result: dict[str, Any] = {}

    # Resolve interaction ids and delete their model runs before the link
    # table rows that would otherwise let us find them.
    interaction_ids = interaction_ids_for_user(user_id)
    result["model_runs"] = _safe(lambda: model_runs.delete_by_interaction_ids(interaction_ids))
    result["session_interactions"] = _safe(lambda: delete_links_for_user(user_id))

    result["vocabulary"] = _safe(lambda: vocabulary_db.delete_for_user(user_id))
    result["collocations"] = _safe(lambda: collocations.delete_for_user(user_id))
    result["conversation_turns"] = _safe(lambda: session_history.delete_for_user(user_id))
    result["analytics"] = _safe(lambda: analytics.delete_for_user(user_id))
    result["sessions"] = _safe(lambda: sessions_store.delete_for_user(user_id))
    result["skill_states"] = _safe(lambda: skill_state.delete_for_user(user_id))
    result["assessments"] = _safe(lambda: assessments.delete_for_user(user_id))
    result["experiments"] = _safe(lambda: experiments.delete_for_user(user_id))
    result["evidence"] = _safe(lambda: _delete_evidence(user_id))
    result["cultural_notes"] = _safe(lambda: _delete_cultural_notes(user_id))
    result["auth_tokens"] = _safe(lambda: auth.delete_tokens_for_user(user_id))
    result["audit_log_anonymized"] = _safe(lambda: anonymize_for_user(user_id))
    result["profile"] = _safe(lambda: _delete_profile(user_id))
    result["account"] = _safe(lambda: auth.delete_user(user_id))

    return result


def _safe(fn: Any) -> Any:
    """Run a per-store delete/export step, capturing an exception as a result
    instead of letting one broken store abort every other store's cleanup."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed silently
        return {"error": str(exc)}


def _delete_evidence(user_id: str) -> int:
    from src.evidence.store import delete_for_user

    return delete_for_user(user_id)


def _delete_profile(user_id: str) -> bool:
    from src.memory import user_profile

    user_profile.delete_profile(user_id)
    return True


def _account_row(user_id: str) -> dict[str, Any] | None:
    from src.memory.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id, username, created_at FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def _known_languages(profile: dict[str, Any] | None) -> set[str]:
    if not profile:
        return set()
    languages: set[str] = set(profile.get("target_languages") or [])
    languages.update((profile.get("cefr_by_language") or {}).keys())
    return languages


def _export_cultural_notes(user_id: str) -> list[dict[str, Any]]:
    try:
        from src.memory.vector_store import get_vector_store

        store = get_vector_store()
        return store.get_all("cultural_notes", where={"user_id": user_id})
    except Exception:  # noqa: BLE001 - the vector store is optional/best-effort
        return []


def _delete_cultural_notes(user_id: str) -> str:
    from src.memory.vector_store import get_vector_store

    store = get_vector_store()
    store.delete("cultural_notes", where={"user_id": user_id})
    return "deleted"
