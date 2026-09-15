"""Progress analytics — read-only aggregation queries for dashboards.

Pure functions over the SQLite analytics tables (``learning_sessions``,
``error_patterns``) and the ``vocabulary`` store. They return chart-ready
series and rankings for the progress endpoints and the CLI/Gradio summaries.
Nothing here mutates state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.memory import analytics
from src.memory.db import get_connection


def _date_of(iso_timestamp: str) -> str:
    """Return the YYYY-MM-DD date part of an ISO timestamp."""
    return iso_timestamp[:10]


def vocabulary_growth(
    user_id: str, language: str | None = None, *, days: int = 30
) -> list[dict[str, Any]]:
    """Cumulative vocabulary learned per day over the last ``days``.

    Returns a list of ``{"date", "new_words", "cumulative"}`` ordered by date,
    derived from ``learning_sessions.new_words_learned``.
    """
    analytics.init_db()
    with get_connection() as conn:
        clause = "user_id = ?"
        params: list[Any] = [user_id]
        if language is not None:
            clause += " AND language = ?"
            params.append(language)
        rows = conn.execute(
            f"SELECT timestamp, new_words_learned FROM learning_sessions "
            f"WHERE {clause} ORDER BY timestamp",
            params,
        ).fetchall()

    cutoff = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    per_day: dict[str, int] = {}
    for row in rows:
        day = _date_of(row["timestamp"])
        if day < cutoff:
            continue
        per_day[day] = per_day.get(day, 0) + int(row["new_words_learned"] or 0)

    series: list[dict[str, Any]] = []
    cumulative = 0
    for day in sorted(per_day):
        cumulative += per_day[day]
        series.append({"date": day, "new_words": per_day[day], "cumulative": cumulative})
    return series


def top_weaknesses(
    user_id: str, language: str | None = None, *, limit: int = 5
) -> list[dict[str, Any]]:
    """Top unmastered grammar weaknesses, most frequent first.

    Returns ``{"error_type", "occurrences", "last_occurrence"}`` rows.
    """
    analytics.init_db()
    with get_connection() as conn:
        clause = "user_id = ? AND mastered = 0"
        params: list[Any] = [user_id]
        if language is not None:
            clause += " AND language = ?"
            params.append(language)
        rows = conn.execute(
            f"SELECT error_type, occurrences, last_occurrence FROM error_patterns "
            f"WHERE {clause} ORDER BY occurrences DESC, last_occurrence DESC LIMIT ?",
            [*params, limit],
        ).fetchall()
    return [dict(r) for r in rows]


def cefr_progression(user_id: str, language: str | None = None) -> list[dict[str, Any]]:
    """CEFR estimates over time from assessment/session logs.

    Returns ``{"date", "cefr"}`` for sessions that recorded a CEFR estimate,
    ordered by date.
    """
    analytics.init_db()
    with get_connection() as conn:
        clause = "user_id = ? AND cefr_estimate IS NOT NULL"
        params: list[Any] = [user_id]
        if language is not None:
            clause += " AND language = ?"
            params.append(language)
        rows = conn.execute(
            f"SELECT timestamp, cefr_estimate FROM learning_sessions "
            f"WHERE {clause} ORDER BY timestamp",
            params,
        ).fetchall()
    return [{"date": _date_of(r["timestamp"]), "cefr": r["cefr_estimate"]} for r in rows]


def _session_dates(user_id: str, language: str | None) -> list[str]:
    analytics.init_db()
    with get_connection() as conn:
        clause = "user_id = ?"
        params: list[Any] = [user_id]
        if language is not None:
            clause += " AND language = ?"
            params.append(language)
        rows = conn.execute(
            f"SELECT DISTINCT substr(timestamp, 1, 10) AS day FROM learning_sessions "
            f"WHERE {clause} ORDER BY day",
            params,
        ).fetchall()
    return [r["day"] for r in rows]


def current_streak(user_id: str, language: str | None = None, *, today: str | None = None) -> int:
    """Consecutive-day study streak ending today (or yesterday).

    A streak counts back from today through consecutive days with at least one
    session. If there is no session today but there was one yesterday, the
    streak still counts (the user hasn't studied yet today).
    """
    days = set(_session_dates(user_id, language))
    if not days:
        return 0

    ref = datetime.fromisoformat(today).date() if today else datetime.now(UTC).date()
    # Allow the streak to be anchored at today or yesterday.
    if ref.isoformat() not in days:
        ref = ref - timedelta(days=1)
        if ref.isoformat() not in days:
            return 0

    streak = 0
    cursor = ref
    while cursor.isoformat() in days:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def progress_overview(user_id: str, language: str | None = None) -> dict[str, Any]:
    """A compact summary combining the key progress metrics for dashboards."""
    analytics.init_db()
    growth = vocabulary_growth(user_id, language)
    progression = cefr_progression(user_id, language)
    with get_connection() as conn:
        clause = "user_id = ?"
        params: list[Any] = [user_id]
        if language is not None:
            clause += " AND language = ?"
            params.append(language)
        total_sessions = conn.execute(
            f"SELECT COUNT(*) AS n FROM learning_sessions WHERE {clause}", params
        ).fetchone()["n"]

    return {
        "total_sessions": int(total_sessions),
        "current_streak": current_streak(user_id, language),
        "words_learned_total": growth[-1]["cumulative"] if growth else 0,
        "current_cefr": progression[-1]["cefr"] if progression else None,
        "top_weaknesses": top_weaknesses(user_id, language),
    }
