"""Personalized learning paths (ADR-0033).

A learning path is the learner-specific ordering of the curriculum's
objectives, with each one's state:

| state | meaning |
|---|---|
| ``mastered`` | posterior P(mastery) >= 0.8 and recall has not decayed |
| ``needs_review`` | mastered, but FSRS retrievability is below the review threshold |
| ``in_progress`` | evidence, not yet mastered, not a weakness |
| ``weak`` | a demonstrated weakness (provisional+ evidence, low mastery) |
| ``blocked`` | a prerequisite is weak: that prerequisite comes first |
| ``assess`` | some evidence, but not enough to place it |
| ``not_started`` | no evidence yet |

Ordering is prerequisites first, then CEFR level, then id, so the order is
deterministic. Then:

- **short term:** the next few objectives to work on — weak, assess, review,
  in progress, then new;
- **long term:** every objective up to the target level that is not
  mastered;
- **prerequisite gaps:** blocked objectives and the weak prerequisites
  blocking them;
- **skill balance:** recent practice share against the goal's target share;
- **recurrent errors:** objectives failed in two or more sessions;
- **changes:** every state change since the previous path, each with the
  evidence that caused it.

Activity preferences are not modelled: the app records no evidence of which
activity types a learner prefers or benefits from more. The path does not
guess them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.adaptive.constraints import GOAL_SKILL_WEIGHTS
from src.adaptive.learner_model import LearnerEstimates, SubskillModel
from src.adaptive.memory import MemoryState, replay_memory
from src.adaptive.planner import MASTERED_PROBABILITY, WEAK_PROBABILITY, _recent_share
from src.adaptive.snapshot import CatalogObjective, LearnerSnapshot
from src.evidence.difficulty import CEFR_ORDER
from src.learner.estimation import EvidenceStatus

PATH_VERSION = "adaptive-path-v1"
SHORT_TERM_SIZE = 4
_STATE_PRIORITY = {
    "weak": 0,
    "assess": 1,
    "needs_review": 2,
    "in_progress": 3,
    "not_started": 4,
    "blocked": 5,
    "mastered": 6,
}


@dataclass
class PathStep:
    objective_id: str
    skill: str
    subskill: str
    cefr: str
    state: str
    mastery_probability: float | None
    retrievability: float | None
    prerequisites: list[str]
    blocking_prerequisites: list[str]
    evidence_count: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "skill": self.skill,
            "subskill": self.subskill,
            "cefr": self.cefr,
            "state": self.state,
            "mastery_probability": None
            if self.mastery_probability is None
            else round(self.mastery_probability, 4),
            "retrievability": None
            if self.retrievability is None
            else round(self.retrievability, 4),
            "prerequisites": self.prerequisites,
            "blocking_prerequisites": self.blocking_prerequisites,
            "evidence_count": self.evidence_count,
            "reason": self.reason,
        }


@dataclass
class LearningPath:
    version: str
    user_id: str
    language: str
    generated_at: str
    target_cefr: str
    input_digest: str
    steps: list[PathStep]
    short_term: list[str]
    long_term: list[str]
    prerequisite_gaps: list[dict[str, Any]]
    skill_balance: dict[str, dict[str, float]]
    recurrent_errors: list[dict[str, Any]]
    changes: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "user_id": self.user_id,
            "language": self.language,
            "generated_at": self.generated_at,
            "target_cefr": self.target_cefr,
            "input_digest": self.input_digest,
            "steps": [s.as_dict() for s in self.steps],
            "short_term": self.short_term,
            "long_term": self.long_term,
            "prerequisite_gaps": self.prerequisite_gaps,
            "skill_balance": self.skill_balance,
            "recurrent_errors": self.recurrent_errors,
            "changes": self.changes,
            "notes": self.notes,
        }


def _level(cefr: str) -> int:
    key = cefr.upper()[:2]
    return CEFR_ORDER.index(key) if key in CEFR_ORDER else 0


def _topological(catalog: list[CatalogObjective]) -> list[CatalogObjective]:
    """Prerequisites before dependents; ties by (CEFR, id). Cycles are broken by order."""
    by_id = {o.objective_id: o for o in catalog}
    ordered: list[CatalogObjective] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(o: CatalogObjective) -> None:
        if o.objective_id in placed or o.objective_id in visiting:
            return
        visiting.add(o.objective_id)
        for pre in sorted(o.prerequisites):
            if pre in by_id:
                visit(by_id[pre])
        visiting.discard(o.objective_id)
        placed.add(o.objective_id)
        ordered.append(o)

    for o in sorted(catalog, key=lambda c: (_level(c.cefr), c.objective_id)):
        visit(o)
    return ordered


def _state(
    obj: CatalogObjective,
    estimates: LearnerEstimates,
    memory: dict[str, MemoryState],
    states: dict[str, str],
) -> tuple[str, float | None, float | None, list[str], int, str]:
    has = (obj.skill, obj.subskill) in estimates.subskills
    est = estimates.subskill(obj.skill, obj.subskill)
    mem = memory.get(obj.objective_id)
    r = None if mem is None else mem.retrievability
    blocking = [p for p in obj.prerequisites if states.get(p) in ("weak", "blocked")]
    if blocking:
        return (
            "blocked",
            None,
            r,
            blocking,
            len(est.event_ids),
            (f"prerequisite(s) {', '.join(blocking)} are weak: they come first"),
        )
    if not has:
        return "not_started", None, r, [], 0, "no evidence yet"
    m = est.mastery_probability(obj.difficulty)
    n = len(est.event_ids)
    if est.status == EvidenceStatus.INSUFFICIENT.value:
        return (
            "assess",
            m,
            r,
            [],
            n,
            f"only {est.independent_count} observation(s): not enough to place",
        )
    if m >= MASTERED_PROBABILITY:
        if mem is not None and mem.needs_review:
            return (
                "needs_review",
                m,
                r,
                [],
                n,
                (f"mastered ({m:.0%}) but predicted recall has decayed to {r:.0%}"),
            )
        return "mastered", m, r, [], n, f"mastered: P(success >= 80%) = {m:.0%}"
    if m < WEAK_PROBABILITY and (est.mastery or 0.0) < 0.5:
        return (
            "weak",
            m,
            r,
            [],
            n,
            (
                f"weakness on {est.status} evidence "
                f"(mastery {est.mastery or 0.0:.0%}, {est.pattern})"
            ),
        )
    return "in_progress", m, r, [], n, f"in progress: P(mastery) = {m:.0%}"


def _recurrent_errors(snapshot: LearnerSnapshot) -> list[dict[str, Any]]:
    failures: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for row in snapshot.evidence:
        if str(row.get("assessment") or "").lower() != "incorrect":
            continue
        key = row.get("objective_id") or (
            f"{row.get('skill')}.{row.get('subskill')}" if row.get("subskill") else None
        )
        if not key:
            continue
        failures.setdefault(str(key), set()).add(str(row.get("session_id") or "(none)"))
        counts[str(key)] = counts.get(str(key), 0) + 1
    return [
        {"objective_id": k, "failures": counts[k], "sessions": len(v)}
        for k, v in sorted(failures.items(), key=lambda kv: (-counts[kv[0]], kv[0]))
        if len(v) >= 2
    ]


def _skill_balance(snapshot: LearnerSnapshot) -> dict[str, dict[str, float]]:
    share = _recent_share(snapshot)
    weights = GOAL_SKILL_WEIGHTS.get(snapshot.goal, {})
    skills = sorted(set(share) | set(weights))
    total_w = sum(weights.get(s, 1.0) for s in skills) or 1.0
    return {
        s: {
            "recent_share": round(share.get(s, 0.0), 4),
            "target_share": round(weights.get(s, 1.0) / total_w, 4),
        }
        for s in skills
    }


def _changes(previous: dict[str, Any] | None, steps: list[PathStep]) -> list[dict[str, Any]]:
    if not previous:
        return []
    before = {s["objective_id"]: s for s in previous.get("steps", [])}
    out: list[dict[str, Any]] = []
    for step in steps:
        old = before.get(step.objective_id)
        if old is None:
            out.append(
                {
                    "objective_id": step.objective_id,
                    "from": None,
                    "to": step.state,
                    "reason": "added to the path",
                }
            )
            continue
        if old.get("state") != step.state:
            out.append(
                {
                    "objective_id": step.objective_id,
                    "from": old.get("state"),
                    "to": step.state,
                    "reason": step.reason,
                    "evidence_count_before": old.get("evidence_count"),
                    "evidence_count_after": step.evidence_count,
                }
            )
    return out


def build_path(
    snapshot: LearnerSnapshot,
    *,
    model: SubskillModel | None = None,
    estimates: LearnerEstimates | None = None,
    memory: dict[str, MemoryState] | None = None,
) -> LearningPath:
    """Build the learner's path from a snapshot (pure; see module docstring)."""
    estimates = estimates or (model or SubskillModel()).estimate(snapshot.evidence)
    memory = memory if memory is not None else replay_memory(snapshot.evidence, snapshot.now)
    states: dict[str, str] = {}
    steps: list[PathStep] = []
    for obj in _topological(snapshot.catalog):
        state, m, r, blocking, n, reason = _state(obj, estimates, memory, states)
        states[obj.objective_id] = state
        steps.append(
            PathStep(
                objective_id=obj.objective_id,
                skill=obj.skill,
                subskill=obj.subskill,
                cefr=obj.cefr,
                state=state,
                mastery_probability=m,
                retrievability=r,
                prerequisites=list(obj.prerequisites),
                blocking_prerequisites=blocking,
                evidence_count=n,
                reason=reason,
            )
        )
    target = _level(snapshot.target_cefr)
    in_scope = [s for s in steps if _level(s.cefr) <= target]
    order = {s.objective_id: i for i, s in enumerate(steps)}
    actionable = sorted(
        (s for s in in_scope if s.state not in ("mastered", "blocked")),
        key=lambda s: (_STATE_PRIORITY[s.state], order[s.objective_id]),
    )
    # At most one not-started objective in the short term: no overload.
    short: list[str] = []
    new_taken = False
    for s in actionable:
        if s.state == "not_started":
            if new_taken:
                continue
            new_taken = True
        short.append(s.objective_id)
        if len(short) >= SHORT_TERM_SIZE:
            break
    gaps = [
        {"objective_id": s.objective_id, "blocked_by": s.blocking_prerequisites}
        for s in steps
        if s.state == "blocked"
    ]
    path = LearningPath(
        version=PATH_VERSION,
        user_id=snapshot.user_id,
        language=snapshot.language,
        generated_at=snapshot.now_iso,
        target_cefr=snapshot.target_cefr,
        input_digest=snapshot.digest(),
        steps=steps,
        short_term=short,
        long_term=[s.objective_id for s in in_scope if s.state != "mastered"],
        prerequisite_gaps=gaps,
        skill_balance=_skill_balance(snapshot),
        recurrent_errors=_recurrent_errors(snapshot),
        notes=[
            "activity preferences are not modelled: there is no evidence of them yet",
        ],
    )
    path.changes = _changes(snapshot.previous_path, steps)
    return path
