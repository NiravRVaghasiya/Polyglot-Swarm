"""Predictive learner performance (ADR-0033).

Every value returned here is labelled ``"kind": "prediction"`` and stated
``as_of`` a time. Observed results live in the evidence store and are never
mixed in. Predictions are built from evidence strictly before ``as_of``
(:func:`~src.adaptive.learner_model.evidence_before`), so asking about the
past cannot use what happened later.

Provided:

- ``p_success`` of a task on a skill/subskill at a difficulty, with an
  interval;
- an expected-performance curve across difficulty levels;
- the likelihood of forgetting an item (FSRS retrievability replayed from
  demonstrated recall);
- the probability that a learning objective is completed (mastered);
- the areas that need assessment.
"""

from __future__ import annotations

from typing import Any

from src.adaptive.difficulty import performance_curve
from src.adaptive.learner_model import (
    LearnerEstimates,
    SubskillModel,
    evidence_before,
    predict_success,
)
from src.adaptive.memory import item_key, replay_memory
from src.adaptive.snapshot import LearnerSnapshot
from src.learner.estimation import EvidenceStatus

#: Uncertainty above which an assessed subskill still needs assessment.
ASSESS_UNCERTAINTY = 0.75


def assessment_needs(
    estimates: LearnerEstimates, snapshot: LearnerSnapshot
) -> list[dict[str, Any]]:
    """Objectives and subskills where more evidence is needed, most uncertain first."""
    needs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for obj in snapshot.catalog:
        has = (obj.skill, obj.subskill) in estimates.subskills
        est = estimates.subskill(obj.skill, obj.subskill)
        seen.add(obj.objective_id)
        if not has:
            needs.append(
                {"objective_id": obj.objective_id, "reason": "never assessed", "uncertainty": 1.0}
            )
        elif est.status == EvidenceStatus.INSUFFICIENT.value:
            needs.append(
                {
                    "objective_id": obj.objective_id,
                    "reason": f"only {est.independent_count} observation(s)",
                    "uncertainty": round(est.uncertainty, 4),
                }
            )
        elif est.pattern == "temporary_dip":
            needs.append(
                {
                    "objective_id": obj.objective_id,
                    "reason": "latest session dipped: confirm before acting",
                    "uncertainty": round(est.uncertainty, 4),
                }
            )
        elif est.uncertainty > ASSESS_UNCERTAINTY:
            needs.append(
                {
                    "objective_id": obj.objective_id,
                    "reason": "wide uncertainty",
                    "uncertainty": round(est.uncertainty, 4),
                }
            )
    for skill, skill_est in sorted(estimates.skills.items()):
        if skill_est.status == EvidenceStatus.INSUFFICIENT.value and f"skill:{skill}" not in seen:
            needs.append(
                {
                    "objective_id": f"skill:{skill}",
                    "reason": f"{skill}: insufficient evidence",
                    "uncertainty": round(skill_est.uncertainty, 4),
                }
            )
    return sorted(needs, key=lambda n: (-float(n["uncertainty"]), str(n["objective_id"])))


def predictions_for(
    snapshot: LearnerSnapshot,
    *,
    skill: str,
    subskill: str | None = None,
    difficulty: float | None = None,
    model: SubskillModel | None = None,
) -> dict[str, Any]:
    """All predictions about one skill/subskill as of the snapshot's ``now``."""
    as_of = snapshot.now_iso
    history = evidence_before(snapshot.evidence, as_of)
    estimates = (model or SubskillModel()).estimate(history)
    est = estimates.subskill(skill, subskill)
    objective = next(
        (o for o in snapshot.catalog if o.skill == skill and o.subskill == subskill), None
    )
    content = objective.difficulty if objective is not None else None
    pred = predict_success(
        estimates, skill, subskill, difficulty if difficulty is not None else content, as_of=as_of
    )
    memory = replay_memory(history, snapshot.now)
    key = item_key({"skill": skill, "subskill": subskill, "item_id": subskill})
    mem = memory.get(key) if key else None
    return {
        "kind": "prediction",
        "as_of": as_of,
        "skill": skill,
        "subskill": subskill,
        "success": pred.as_dict(),
        "performance_curve": performance_curve(est),
        "objective_completion_probability": round(est.mastery_probability(content), 4)
        if objective is not None
        else None,
        "forgetting": None
        if mem is None
        else {
            "retrievability": None if mem.retrievability is None else round(mem.retrievability, 4),
            "forgetting_risk": None
            if mem.forgetting_risk is None
            else round(mem.forgetting_risk, 4),
            "demonstrated": mem.demonstrated,
            "leech": mem.leech,
        },
        "estimate": est.as_dict(),
        "assessment_needs": assessment_needs(estimates, snapshot)[:10],
    }
