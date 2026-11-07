"""Shared helpers for the adaptive-learning tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.adaptive.snapshot import CatalogObjective, LearnerSnapshot
from src.config import settings

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


_COUNTER = {"n": 0}


def grammar_row(
    construction: str,
    correct: bool,
    *,
    day: float,
    session: str | None = None,
    difficulty: float | None = 0.25,
    item: str | None = None,
    confidence: float = 0.95,
    correlation: str | None = None,
    user: str = "u1",
) -> dict[str, Any]:
    _COUNTER["n"] += 1
    n = _COUNTER["n"]
    return {
        "event_id": f"g{n}",
        "event_type": "GRAMMAR_SUCCESS" if correct else "GRAMMAR_ERROR",
        "user_id": user,
        "language": "Spanish",
        "skill": "grammar",
        "subskill": construction,
        "objective_id": f"grammar.{construction}",
        "item_id": item or f"{construction}#{n}",
        "assessment": "correct" if correct else "incorrect",
        "confidence": confidence,
        "task_type": "exercise",
        "difficulty": difficulty,
        "difficulty_basis": "cefr_label" if difficulty is not None else "unknown",
        "session_id": session or f"s{int(day)}",
        "correlation_id": correlation,
        "source": "test",
        "created_at": (T0 + timedelta(days=day)).isoformat(),
        "payload": {},
    }


def vocab_row(
    word: str,
    *,
    day: float,
    assessment: str,
    mode: str = "recognition",
    event_type: str = "REVIEW_RESULT",
    correlation: str | None = None,
) -> dict[str, Any]:
    _COUNTER["n"] += 1
    n = _COUNTER["n"]
    return {
        "event_id": f"v{n}",
        "event_type": event_type,
        "user_id": "u1",
        "language": "Spanish",
        "skill": "vocabulary",
        "subskill": mode,
        "objective_id": f"vocabulary.{mode}",
        "item_id": word,
        "assessment": assessment,
        "confidence": 0.95,
        "session_id": f"s{int(day)}",
        "correlation_id": correlation,
        "source": "test",
        "created_at": (T0 + timedelta(days=day)).isoformat(),
        "payload": {},
    }


CATALOG = [
    CatalogObjective("grammar.gender_agreement", "grammar", "gender_agreement", "A1", 1 / 12),
    CatalogObjective("grammar.ser_vs_estar", "grammar", "ser_vs_estar", "A2", 3 / 12),
    CatalogObjective(
        "grammar.preterite_vs_imperfect",
        "grammar",
        "preterite_vs_imperfect",
        "B1",
        5 / 12,
        ("grammar.gender_agreement",),
    ),
    CatalogObjective(
        "grammar.subjunctive_present",
        "grammar",
        "subjunctive_present",
        "B2",
        7 / 12,
        ("grammar.ser_vs_estar",),
    ),
]


def snapshot(
    evidence: list[dict[str, Any]],
    *,
    day: float = 30.0,
    vocabulary: list[dict[str, Any]] | None = None,
    catalog: list[CatalogObjective] | None = None,
    **kw: Any,
) -> LearnerSnapshot:
    return LearnerSnapshot(
        user_id="u1",
        language="Spanish",
        now=T0 + timedelta(days=day),
        evidence=evidence,
        vocabulary=vocabulary or [],
        catalog=CATALOG if catalog is None else catalog,
        **kw,
    )
