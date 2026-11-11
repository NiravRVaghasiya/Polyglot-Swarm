"""The learner snapshot: every input the adaptive engine reads, in one value.

The engine (:mod:`src.adaptive.planner`, :mod:`src.adaptive.paths`) is a pure
function of a :class:`LearnerSnapshot`. :func:`snapshot_from_store` builds one
from the app's stores; the evaluation simulator builds one from simulated
state. Both therefore exercise exactly the same decision code.

``now`` is explicit. Evidence after ``now`` is dropped, so a snapshot of the
past never sees the future.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.adaptive.learner_model import evidence_before
from src.evidence.difficulty import cefr_to_difficulty


@dataclass(frozen=True)
class CatalogObjective:
    """A learning objective the curriculum knows about."""

    objective_id: str  # e.g. "grammar.ser_vs_estar"
    skill: str
    subskill: str
    cefr: str
    difficulty: float | None  # content (linguistic) difficulty in [0, 1]
    prerequisites: tuple[str, ...] = ()


@dataclass
class LearnerSnapshot:
    user_id: str
    language: str
    now: datetime
    evidence: list[dict[str, Any]]
    vocabulary: list[dict[str, Any]] = field(default_factory=list)
    catalog: list[CatalogObjective] = field(default_factory=list)
    goal: str = "conversational"
    #: The learner's target level (long-term objectives stop here).
    target_cefr: str = "B1"
    #: The previous learning path (for explaining changes), if any.
    previous_path: dict[str, Any] | None = None
    #: Last recommended task difficulty per objective (for bounded steps).
    last_difficulty: dict[str, float] = field(default_factory=dict)
    #: Words available for vocabulary expansion (none in the app yet: new
    #: words arrive through conversation).
    new_words: list[str] = field(default_factory=list)

    @property
    def now_iso(self) -> str:
        return self.now.isoformat()

    def digest(self) -> str:
        """A short hash identifying the snapshot's inputs (for audit records)."""
        blob = json.dumps(
            {
                "user": self.user_id,
                "language": self.language,
                "now": self.now_iso,
                "evidence": sorted(str(r.get("event_id")) for r in self.evidence),
                "vocabulary": sorted(
                    (str(v.get("word")), str(v.get("next_review"))) for v in self.vocabulary
                ),
                "catalog": [c.objective_id for c in self.catalog],
                "goal": self.goal,
                "target": self.target_cefr,
                "last_difficulty": sorted(self.last_difficulty.items()),
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:24]


def catalog_for_language(language: str) -> list[CatalogObjective]:
    """Grammar objectives from the language pack (empty if there is no pack)."""
    try:
        from src.languages import list_constructions

        items = sorted(list_constructions(language), key=lambda c: (c.cefr, c.construction))
    except Exception:  # noqa: BLE001 - no pack, no catalog
        return []
    return [
        CatalogObjective(
            objective_id=f"grammar.{item.construction}",
            skill="grammar",
            subskill=item.construction,
            cefr=item.cefr,
            difficulty=cefr_to_difficulty(item.cefr),
            prerequisites=tuple(f"grammar.{p}" for p in item.prerequisites),
        )
        for item in items
    ]


def snapshot_from_store(
    user_id: str,
    language: str,
    *,
    now: datetime | None = None,
    goal: str = "conversational",
    target_cefr: str | None = None,
) -> LearnerSnapshot:
    """Build a snapshot from the evidence, vocabulary, profile and audit stores."""
    from src.adaptive import audit
    from src.evidence import store
    from src.memory import vocabulary_db

    now = now or datetime.now(UTC)
    evidence = [
        r
        for r in store.active_events(user_id, language)
        if r.get("created_at") and str(r["created_at"]) <= now.isoformat()
    ]
    if target_cefr is None:
        target_cefr = _target_from_profile(user_id, language)
    previous = audit.last_decision(user_id, language, kind="path")
    last_rec = audit.last_decision(user_id, language, kind="recommendation")
    last_difficulty: dict[str, float] = {}
    if last_rec:
        for rec in last_rec.get("payload", {}).get("recommendations", []):
            d = (rec.get("difficulty") or {}).get("task_difficulty")
            if rec.get("objective_id") and d is not None:
                last_difficulty[str(rec["objective_id"])] = float(d)
    return LearnerSnapshot(
        user_id=user_id,
        language=language,
        now=now,
        evidence=evidence_before(evidence, None),
        vocabulary=vocabulary_db.get_all_for_user(user_id, language),
        catalog=catalog_for_language(language),
        goal=goal,
        target_cefr=target_cefr,
        previous_path=(previous or {}).get("payload"),
        last_difficulty=last_difficulty,
    )


def _target_from_profile(user_id: str, language: str) -> str:
    """One CEFR level above the learner's working level (default B1)."""
    from src.learner.cefr_bands import CEFR_ORDER

    try:
        from src.memory import user_profile

        level = (
            user_profile.load_profile(user_id).cefr_by_language.get(language)
            if user_profile.profile_exists(user_id)
            else None
        )
    except Exception:  # noqa: BLE001 - no profile, default target
        level = None
    if not level or level.upper()[:2] not in CEFR_ORDER:
        return "B1"
    idx = CEFR_ORDER.index(level.upper()[:2])
    return CEFR_ORDER[min(len(CEFR_ORDER) - 1, idx + 1)]
