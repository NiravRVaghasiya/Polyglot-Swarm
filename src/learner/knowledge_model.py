"""Knowledge model facade — read, update, replay, and snapshot the learner model.

This is the seam the rest of the app talks to. Since ADR-0031 the model is a
**projection of the evidence store**, not an incrementally mutated counter:

- :meth:`KnowledgeModel.update_from_events` records the given evidence
  (idempotent on ``event_id``) and then :meth:`recompute`\\s;
- :meth:`recompute` replays the learner's *active* (non-superseded) evidence
  through the pure :class:`~src.learner.estimation.EvidenceMasteryEngine`,
  materializes the result into ``skill_states``, and appends history
  (``lkm_processing_runs`` / ``mastery_updates``) only when the evidence digest
  changed — so applying the same events twice changes nothing;
- :meth:`replay` recomputes an estimate exactly as of a past processing run;
- :meth:`explain` lists how every evidence event entered a skill estimate.

The pre-ADR-0031 incremental engine (:class:`MasteryEngine`) is still run over
the same evidence as a comparison baseline (``baseline_mastery``).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.learner.estimation import METHOD, EvidenceMasteryEngine, SkillEstimate
from src.learner.mastery_engine import MasteryEngine, SkillBelief
from src.memory import skill_state
from src.memory.db import get_connection
from src.memory.schema import init_all


def _catalogs(language: str) -> dict[str, list[tuple[str, float | None]]]:
    """Known objectives per skill (grammar constructions from the language pack)."""
    try:
        from src.evidence.difficulty import cefr_to_difficulty
        from src.languages import list_constructions

        grammar = [
            (f"grammar.{item.construction}", cefr_to_difficulty(item.cefr))
            for item in list_constructions(language)
        ]
    except Exception:  # noqa: BLE001 - a missing/broken pack just means no catalog
        return {}
    return {"grammar": grammar} if grammar else {}


def coerce_event(row: dict[str, Any], user_id: str, language: str) -> Any:
    """Turn an evidence dict (a full event dump or a bare ``{skill, assessment,
    confidence}`` dict) into a :class:`LearningEvent` for the given learner.

    Bare dicts get a fresh ``event_id`` and the generic ``SKILL_EVIDENCE``
    type. Their content fingerprint is identical when their content is, so
    repeating the same bare dict is still counted once by the engine.
    """
    from src.evidence.events import EventType, LearningEvent

    data = {k: v for k, v in row.items() if v is not None and k not in ("id", "fingerprint")}
    data.setdefault("event_id", uuid.uuid4().hex)
    data.setdefault("event_type", EventType.SKILL_EVIDENCE.value)
    data["user_id"] = user_id
    data["language"] = language
    data.setdefault("source", "direct")
    if isinstance(data.get("payload"), str):
        data["payload"] = json.loads(data["payload"])
    if "skill" not in data:
        from src.evidence.events import EVENT_SKILL

        default_skill = EVENT_SKILL.get(EventType(data["event_type"]))
        if default_skill is not None:
            data["skill"] = default_skill
    known = set(LearningEvent.model_fields)
    return LearningEvent.model_validate({k: v for k, v in data.items() if k in known})


class KnowledgeModel:
    """The learner's persistent skill model, projected from the evidence store."""

    def __init__(
        self,
        engine: MasteryEngine | None = None,
        estimator: EvidenceMasteryEngine | None = None,
    ) -> None:
        #: The legacy incremental engine, kept as a comparison baseline.
        self._engine = engine or MasteryEngine()
        self._estimator = estimator or EvidenceMasteryEngine()

    # --- Read ---------------------------------------------------------------

    def current_beliefs(self, user_id: str, language: str) -> dict[str, SkillBelief]:
        """Return the materialized per-skill beliefs (legacy shape), keyed by skill."""
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
        """Convenience: just the materialized mastery scores, keyed by skill."""
        return {s: b.mastery for s, b in self.current_beliefs(user_id, language).items()}

    def current_estimates(
        self,
        user_id: str,
        language: str,
        *,
        with_contributions: bool = False,
    ) -> dict[str, SkillEstimate]:
        """Compute every skill estimate from the active evidence (no writes)."""
        from src.evidence import store

        rows = store.active_events(user_id, language)
        return self._estimator.estimate_all(
            rows, catalogs=_catalogs(language), with_contributions=with_contributions
        )

    def explain(self, user_id: str, language: str, skill: str) -> SkillEstimate | None:
        """Return one skill's estimate with a per-event contribution breakdown."""
        return self.current_estimates(user_id, language, with_contributions=True).get(skill)

    # --- Update -------------------------------------------------------------

    def update_from_events(
        self,
        user_id: str,
        language: str,
        events: list[dict[str, Any]],
        *,
        trigger: str = "update",
    ) -> dict[str, SkillBelief]:
        """Record a batch of evidence, recompute, and return the touched skills.

        Events already in the store (same ``event_id``) are not recorded again,
        so calling this twice with the same events leaves the model unchanged.
        Returns the legacy-shaped beliefs of the skills those events concern.
        """
        from src.evidence import store

        records = [coerce_event(e, user_id, language) for e in events]
        store.record_events(records)
        estimates = self.recompute(user_id, language, trigger=trigger)
        touched = {r.skill for r in records if r.skill}
        return {
            skill: estimates[skill].to_belief()
            for skill in sorted(touched)
            if skill in estimates and estimates[skill].mastery is not None
        }

    def update_from_store(
        self,
        user_id: str,
        language: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, SkillBelief]:
        """Recompute from the evidence store. ``session_id`` is accepted for
        compatibility; the model always replays the full active evidence set."""
        estimates = self.recompute(user_id, language, trigger="update_from_store")
        return {s: e.to_belief() for s, e in estimates.items() if e.mastery is not None}

    def recompute(
        self, user_id: str, language: str, *, trigger: str = "recompute"
    ) -> dict[str, SkillEstimate]:
        """Replay the active evidence, materialize it, and record what changed.

        Idempotent: when the evidence digest equals the latest run's, nothing is
        written. Otherwise one processing run plus one ``mastery_updates`` row
        per changed skill are appended, and ``skill_states`` is rewritten.
        """
        from src.evidence import store
        from src.memory import lkm_history

        rows = store.active_events(user_id, language)
        ev_hw, sup_hw = store.high_water_marks(user_id)
        estimates = self._estimator.estimate_all(rows, catalogs=_catalogs(language))
        digest = self._overall_digest(estimates)

        previous = lkm_history.latest_run(user_id, language)
        if previous is not None and previous["evidence_digest"] == digest:
            return estimates

        before = skill_state.get_skills(user_id, language)
        prev_ids = self._event_ids_by_skill(user_id, language, previous)
        updates: list[dict[str, Any]] = []
        for skill, est in estimates.items():
            prior = before.get(skill)
            unchanged = prior is not None and prior.get("evidence_digest") == est.evidence_digest
            if est.mastery is None:
                if prior is not None:
                    skill_state.delete_skill(user_id, language, skill)
            elif not unchanged:
                skill_state.upsert_estimate(
                    user_id,
                    language,
                    skill,
                    mastery=est.mastery,
                    uncertainty=est.uncertainty,
                    sample_size=est.graded_count,
                    method=est.method,
                    status=est.status,
                    mastery_low=est.mastery_low,
                    mastery_high=est.mastery_high,
                    evidence_index=est.evidence_index,
                    independent_n=float(est.independent_count),
                    effective_n=est.effective_n,
                    evidence_quality=est.quality.score(),
                    baseline_mastery=est.baseline_mastery,
                    coverage=est.as_dict()["coverage"],
                    last_evidence_at=est.last_evidence_at,
                    evidence_digest=est.evidence_digest,
                )
            if unchanged:
                continue
            old_ids = prev_ids.get(skill, set())
            new_ids = set(est.event_ids)
            updates.append(
                {
                    "skill": skill,
                    "evidence_digest": est.evidence_digest,
                    "mastery_before": None if prior is None else prior.get("mastery"),
                    "mastery_after": est.mastery,
                    "uncertainty_after": est.uncertainty,
                    "status_before": None if prior is None else prior.get("status"),
                    "status_after": est.status,
                    "baseline_mastery": est.baseline_mastery,
                    "independent_n": float(est.independent_count),
                    "new_event_ids": sorted(new_ids - old_ids),
                    "removed_event_ids": sorted(old_ids - new_ids),
                }
            )
        # Skills whose evidence was entirely retracted.
        for skill, prior in before.items():
            if skill not in estimates and prior.get("method") == METHOD:
                skill_state.delete_skill(user_id, language, skill)
                updates.append(
                    {
                        "skill": skill,
                        "evidence_digest": "",
                        "mastery_before": prior.get("mastery"),
                        "mastery_after": None,
                        "status_before": prior.get("status"),
                        "status_after": None,
                        "removed_event_ids": sorted(prev_ids.get(skill, set())),
                    }
                )

        lkm_history.record_run(
            user_id,
            language,
            method=METHOD,
            trigger=trigger,
            evidence_digest=digest,
            evidence_count=len(rows),
            evidence_high_water=ev_hw,
            supersession_high_water=sup_hw,
            updates=updates,
        )
        return estimates

    # --- Replay / history ----------------------------------------------------

    def replay(
        self, user_id: str, language: str, *, run_id: int | None = None
    ) -> dict[str, SkillEstimate]:
        """Recompute estimates as of processing run ``run_id`` (latest if ``None``).

        Pure (writes nothing). Reconstructs the active evidence set from the
        run's high-water marks, so the result is reproducible later even after
        more evidence or corrections have been recorded.
        """
        from src.evidence import store
        from src.memory import lkm_history

        run = (
            lkm_history.get_run(run_id)
            if run_id is not None
            else lkm_history.latest_run(user_id, language)
        )
        if run is None:
            return {}
        rows = store.active_events(
            user_id,
            language,
            evidence_high_water=int(run["evidence_high_water"]),
            supersession_high_water=int(run["supersession_high_water"]),
        )
        return self._estimator.estimate_all(rows, catalogs=_catalogs(language))

    def history(
        self, user_id: str, language: str, *, skill: str | None = None
    ) -> list[dict[str, Any]]:
        """Return the per-skill mastery-update history, oldest first."""
        from src.memory import lkm_history

        return lkm_history.get_updates(user_id, language, skill=skill)

    def _event_ids_by_skill(
        self, user_id: str, language: str, run: dict[str, Any] | None
    ) -> dict[str, set[str]]:
        if run is None:
            return {}
        estimates = self.replay(user_id, language, run_id=int(run["id"]))
        return {s: set(e.event_ids) for s, e in estimates.items()}

    @staticmethod
    def overall_digest(estimates: dict[str, SkillEstimate]) -> str:
        """The digest identifying a whole learner model (all skills)."""
        return KnowledgeModel._overall_digest(estimates)

    @staticmethod
    def _overall_digest(estimates: dict[str, SkillEstimate]) -> str:
        blob = "|".join(f"{s}:{e.evidence_digest}" for s, e in sorted(estimates.items()))
        return hashlib.sha256(f"{METHOD}|{blob}".encode()).hexdigest()[:32]

    # --- Snapshot -----------------------------------------------------------

    def snapshot(self, user_id: str, language: str, *, reason: str = "manual") -> int:
        """Persist an immutable JSON snapshot of the current model. Returns row id.

        Each skill carries the legacy fields (mastery/uncertainty/sample_size)
        plus the ADR-0031 status, interval, evidence counts and digest.
        """
        init_all()
        estimates = self.current_estimates(user_id, language)
        payload: dict[str, Any] = {}
        for skill, e in estimates.items():
            payload[skill] = {
                "mastery": None if e.mastery is None else round(e.mastery, 4),
                "uncertainty": round(e.uncertainty, 4),
                "sample_size": e.graded_count,
                "status": e.status,
                "mastery_low": None if e.mastery_low is None else round(e.mastery_low, 4),
                "mastery_high": None if e.mastery_high is None else round(e.mastery_high, 4),
                "independent_count": e.independent_count,
                "cefr": e.cefr,
                "method": e.method,
                "evidence_digest": e.evidence_digest,
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
