"""Knowledge model facade — read, update, and snapshot the learner model.

This is the seam the rest of the app talks to. It:

- reads the current per-skill belief from the ``skill_states`` store,
- pulls evidence from the evidence store (or accepts a supplied batch),
- runs the :class:`MasteryEngine` to compute posteriors,
- persists the posteriors back to ``skill_states``, and
- writes an immutable JSON snapshot of the model for longitudinal analysis /
  rollback (``learner_state_snapshots``).

Storage lives behind this facade so the engine itself stays pure and the
curriculum planner (Phase 7) has one place to read "what can the learner do".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.learner.mastery_engine import MasteryEngine, SkillBelief
from src.memory import skill_state
from src.memory.db import get_connection
from src.memory.schema import init_all


class KnowledgeModel:
    """The learner's persistent skill model, backed by ``skill_states``."""

    def __init__(self, engine: MasteryEngine | None = None) -> None:
        self._engine = engine or MasteryEngine()

    # --- Read ---------------------------------------------------------------

    def current_beliefs(self, user_id: str, language: str) -> dict[str, SkillBelief]:
        """Return the stored per-skill beliefs, keyed by skill."""
        rows = skill_state.get_skills(user_id, language)
        return {
            skill: SkillBelief(
                skill=skill,
                mastery=float(row.get("mastery", 0.0)),
                uncertainty=float(row.get("uncertainty", 1.0)),
                sample_size=float(row.get("sample_size", 0)),
            )
            for skill, row in rows.items()
        }

    def mastery_by_skill(self, user_id: str, language: str) -> dict[str, float]:
        """Convenience: just the mastery scores, keyed by skill."""
        return {s: b.mastery for s, b in self.current_beliefs(user_id, language).items()}

    # --- Update -------------------------------------------------------------

    def update_from_events(
        self,
        user_id: str,
        language: str,
        events: list[dict[str, Any]],
    ) -> dict[str, SkillBelief]:
        """Update skill beliefs from a batch of evidence rows and persist them.

        Returns the posterior beliefs for the skills that were touched.
        """
        priors = self.current_beliefs(user_id, language)
        posteriors = self._engine.update_from_events(priors, events)
        for skill, belief in posteriors.items():
            skill_state.upsert_skill(
                user_id,
                language,
                skill,
                mastery=belief.mastery,
                uncertainty=belief.uncertainty,
                sample_size=int(round(belief.sample_size)),
            )
        return posteriors

    def update_from_store(
        self,
        user_id: str,
        language: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, SkillBelief]:
        """Update beliefs from evidence read out of the evidence store.

        If ``session_id`` is given, only that session's events are applied
        (the usual end-of-session update). Imported lazily to avoid a hard
        dependency cycle with the evidence package.
        """
        from src.evidence import store

        events = store.get_events(user_id, language, session_id=session_id, limit=1000)
        return self.update_from_events(user_id, language, events)

    # --- Snapshot -----------------------------------------------------------

    def snapshot(self, user_id: str, language: str, *, reason: str = "manual") -> int:
        """Persist an immutable JSON snapshot of the current model. Returns row id."""
        init_all()
        beliefs = self.current_beliefs(user_id, language)
        payload = {
            skill: {
                "mastery": round(b.mastery, 4),
                "uncertainty": round(b.uncertainty, 4),
                "sample_size": b.sample_size,
            }
            for skill, b in beliefs.items()
        }
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO learner_state_snapshots
                    (user_id, language, snapshot, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    language,
                    json.dumps(payload),
                    reason,
                    datetime.now(UTC).isoformat(),
                ),
            )
            row_id = cursor.lastrowid
        assert row_id is not None
        return row_id


_MODEL = KnowledgeModel()


def get_knowledge_model() -> KnowledgeModel:
    """Return the shared knowledge-model instance."""
    return _MODEL
