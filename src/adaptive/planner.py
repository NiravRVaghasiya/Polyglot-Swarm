"""Next-best learning activity engine (``adaptive-nba-v1``, ADR-0033).

A deterministic, auditable decision layer. No LLM is involved in choosing what
the learner does next. An LLM may later *render* a chosen activity (write the
exercise, play the role); it never selects one.

Pipeline
--------
1. **Estimate.** Compute skill (v2) and subskill (v1) estimates from the
   snapshot's evidence, and replay retention states through FSRS
   (:mod:`src.adaptive.memory`).
2. **Generate candidates.** Every activity the evidence supports:

   | activity | intent | when |
   |---|---|---|
   | ``diagnostic_check`` | assessment | too little evidence, or a one-session dip to confirm |
   | ``grammar_practice`` | remediation | demonstrated weakness (or a weak prerequisite) |
   | ``grammar_practice`` | reinforcement | in progress, not yet mastered |
   | ``grammar_practice`` | progression | mastered at this difficulty: step up |
   | ``grammar_practice`` | introduction | a new construction whose prerequisites are met |
   | ``retention_review`` | review | a demonstrated item whose recall has decayed (FSRS) |
   | ``vocabulary_review`` | review | an FSRS-due word (recognition, then production) |
   | ``vocabulary_remediation`` | remediation | a leech: repeated retrieval failures |
   | ``vocabulary_expansion`` | introduction | little vocabulary in learning |
   | ``conversation_practice`` | reinforcement | contextual practice (always available) |
   | skill activities | per skill evidence | listening / reading / writing / pragmatics |

3. **Score.** Each candidate gets components in ``[0, 1]``: expected learning
   gain, predicted success, retention need, importance, objective relevance,
   uncertainty, coverage gap, urgency, difficulty fit and progression. The
   score is a weighted mean with an explicit weight table per intent
   (:data:`INTENT_WEIGHTS`), times a skill-balance factor and the
   fatigue/time penalty from :class:`~src.curriculum.PlanConstraints`.
4. **De-duplicate.** One recommendation per item or objective. When FSRS and
   the curriculum both want the same item, the review wins and the
   recommendation says both reasons.
5. **Select.** Greedy by score within the time budget. At most
   :data:`MAX_ASSESSMENTS` assessments and :data:`MAX_INTRODUCTIONS` new items
   per plan. Ties break deterministically on (score, intent order, target).

Every recommendation carries:

- the activity and intent;
- the target skill, subskill and learning objective;
- the recommended difficulty decision;
- the predicted success, with its interval;
- the rationale and the expected benefit;
- the evidence it rests on;
- its uncertainty;
- the score components.

The value model encodes learning-science *assumptions*, not measured facts:

- practice is most valuable near ~75% success (desirable difficulty);
- decayed items gain most from retrieval;
- unassessed content is worth probing.

They are tested in simulation only (``evals/adaptive``, results labelled as
simulated). ``PlannerConfig`` switches individual capabilities off for the
ablations in that evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.adaptive.difficulty import TARGET_SUCCESS, DifficultyDecision, choose_difficulty
from src.adaptive.learner_model import (
    LearnerEstimates,
    Pattern,
    SubskillEstimate,
    SubskillModel,
    predict_success,
    prior_subskill,
)
from src.adaptive.memory import (
    REVIEW_THRESHOLD,
    MemoryState,
    live_retrievability,
    replay_memory,
)
from src.adaptive.snapshot import CatalogObjective, LearnerSnapshot
from src.curriculum.constraints import GOAL_SKILL_WEIGHTS, PlanConstraints
from src.evidence.difficulty import CEFR_ORDER
from src.learner.estimation import EvidenceStatus, status_rank

ENGINE = "adaptive-nba-v1"
MAX_ASSESSMENTS = 2
MAX_INTRODUCTIONS = 1
#: Share of the session's time assessments may take: learning always fits.
MAX_ASSESSMENT_SHARE = 0.4
#: Objectives mastered with at least this posterior probability are not
#: practised again without a retention reason.
MASTERED_PROBABILITY = 0.8
#: A grammar objective is "weak" below this mastery probability at its own
#: content difficulty, with at least provisional evidence.
WEAK_PROBABILITY = 0.25
#: Active vocabulary load below which expansion is proposed.
MIN_ACTIVE_WORDS = 8

#: Minutes per activity.
MINUTES: dict[str, float] = {
    "diagnostic_check": 3.0,
    "grammar_practice": 5.0,
    "retention_review": 2.0,
    "vocabulary_review": 1.0,
    "vocabulary_remediation": 3.0,
    "vocabulary_expansion": 3.0,
    "conversation_practice": 8.0,
    "listening_check": 4.0,
    "reading": 6.0,
    "writing_exercise": 6.0,
}

COMPONENTS = (
    "gain",
    "success",
    "retention",
    "importance",
    "relevance",
    "uncertainty",
    "coverage",
    "urgency",
    "difficulty_fit",
    "progression",
)

#: Weight of each score component, per intent. Rows are documented in
#: ``docs/adaptive-learning.md``; zeros mean "irrelevant for this intent".
INTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "review": {
        "gain": 1.0, "success": 0.5, "retention": 3.0, "importance": 1.0, "relevance": 0.5,
        "uncertainty": 0.0, "coverage": 0.0, "urgency": 2.0, "difficulty_fit": 0.5,
        "progression": 0.0,
    },
    "remediation": {
        "gain": 2.0, "success": 0.5, "retention": 0.0, "importance": 1.0, "relevance": 1.0,
        "uncertainty": 0.0, "coverage": 0.0, "urgency": 2.5, "difficulty_fit": 1.0,
        "progression": 0.0,
    },
    "assessment": {
        "gain": 0.5, "success": 0.0, "retention": 0.0, "importance": 1.0, "relevance": 1.0,
        "uncertainty": 2.5, "coverage": 2.0, "urgency": 1.5, "difficulty_fit": 0.0,
        "progression": 0.0,
    },
    "reinforcement": {
        "gain": 2.5, "success": 1.0, "retention": 0.5, "importance": 1.0, "relevance": 1.0,
        "uncertainty": 0.5, "coverage": 0.0, "urgency": 0.5, "difficulty_fit": 1.5,
        "progression": 0.0,
    },
    "progression": {
        "gain": 1.5, "success": 1.0, "retention": 0.0, "importance": 1.0, "relevance": 1.0,
        "uncertainty": 0.0, "coverage": 0.0, "urgency": 0.0, "difficulty_fit": 1.0,
        "progression": 2.0,
    },
    "introduction": {
        "gain": 2.0, "success": 0.5, "retention": 0.0, "importance": 1.0, "relevance": 1.5,
        "uncertainty": 0.0, "coverage": 0.5, "urgency": 0.0, "difficulty_fit": 0.5,
        "progression": 2.0,
    },
}  # fmt: skip

PERSISTENT = (Pattern.PERSISTENT_WEAKNESS, Pattern.PERSISTENT_DECLINE)

#: Deterministic tie-break order of intents.
INTENT_ORDER = (
    "review",
    "remediation",
    "assessment",
    "reinforcement",
    "progression",
    "introduction",
)

#: Skill-level activities for skills without an objective catalog.
_SKILL_ACTIVITY = {
    "listening": "listening_check",
    "reading": "reading",
    "writing": "writing_exercise",
    "pragmatics": "conversation_practice",
    "speaking": "conversation_practice",
}


@dataclass(frozen=True)
class PlannerConfig:
    """Capability switches (all on in the app; off for ablations)."""

    #: Use subskill predictions (lkm-subskill-v1). Off: skill-level v2 only.
    predictive: bool = True
    #: Choose task difficulty adaptively. Off: always the content's level.
    adaptive_difficulty: bool = True
    #: Retention-aware FSRS integration (decayed recall, recognition ->
    #: production, leeches, exposure != recall). Off: due order only.
    fsrs_integration: bool = True
    target_success: float = TARGET_SUCCESS


@dataclass
class Recommendation:
    activity: str
    intent: str
    skill: str
    target: str
    subskill: str | None = None
    objective_id: str | None = None
    difficulty: DifficultyDecision | None = None
    mode: str | None = None  # recognition | production (reviews)
    predicted_success: dict[str, Any] | None = None
    rationale: list[str] = field(default_factory=list)
    expected_benefit: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    components: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    estimated_minutes: float = 0.0
    sources: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """De-duplication key: one recommendation per item/objective."""
        return self.objective_id or f"{self.skill}:{self.target}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "activity": self.activity,
            "intent": self.intent,
            "skill": self.skill,
            "subskill": self.subskill,
            "objective_id": self.objective_id,
            "target": self.target,
            "mode": self.mode,
            "difficulty": None if self.difficulty is None else self.difficulty.as_dict(),
            "predicted_success": self.predicted_success,
            "rationale": list(self.rationale),
            "expected_benefit": self.expected_benefit,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "score": round(self.score, 4),
            "estimated_minutes": self.estimated_minutes,
            "sources": list(self.sources),
        }


@dataclass
class Plan:
    engine: str
    user_id: str
    language: str
    generated_at: str
    input_digest: str
    config: dict[str, Any]
    recommendations: list[Recommendation]
    considered: int
    deferred: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "user_id": self.user_id,
            "language": self.language,
            "generated_at": self.generated_at,
            "input_digest": self.input_digest,
            "config": self.config,
            "recommendations": [r.as_dict() for r in self.recommendations],
            "considered": self.considered,
            "deferred": self.deferred,
        }


# --- helpers --------------------------------------------------------------------


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _zone(p: float, target: float) -> float:
    """Learning value of practising at success probability ``p`` (peaks at target)."""
    return math.exp(-(((p - target) / 0.2) ** 2))


def _level_index(cefr: str | None) -> int:
    key = (cefr or "").upper()[:2]
    return CEFR_ORDER.index(key) if key in CEFR_ORDER else 0


def _importance(skill: str, cefr: str | None, constraints: PlanConstraints, target: str) -> float:
    weight = GOAL_SKILL_WEIGHTS.get(constraints.goal, {}).get(skill, 1.0) / 1.5
    beyond = _level_index(cefr) - _level_index(target)
    level = 1.0 if beyond <= 0 else (0.5 if beyond == 1 else 0.2)
    return _clip(weight * level)


def _evidence_summary(ids: list[str], **extra: Any) -> dict[str, Any]:
    return {"event_count": len(ids), "event_ids": ids[-10:], **extra}


def _uncertainty(est: SubskillEstimate) -> dict[str, Any]:
    return {
        "status": est.status,
        "pattern": est.pattern,
        "ability_se": round(est.ability_se, 4),
        "uncertainty": round(est.uncertainty, 4),
        "mastery_interval": None
        if est.mastery_low is None or est.mastery_high is None
        else [round(est.mastery_low, 4), round(est.mastery_high, 4)],
    }


def _parse(ts: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _recent_share(snapshot: LearnerSnapshot, days: float = 7.0) -> dict[str, float]:
    """Share of graded evidence per skill over the last ``days`` (skill balance)."""
    cutoff = snapshot.now - timedelta(days=days)
    counts: dict[str, int] = {}
    for row in snapshot.evidence:
        ts = _parse(row.get("created_at"))
        if ts is None or ts < cutoff or not row.get("skill"):
            continue
        counts[str(row["skill"])] = counts.get(str(row["skill"]), 0) + 1
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()} if total else {}


def _balance_factor(skill: str, share: dict[str, float], constraints: PlanConstraints) -> float:
    """Up to ±20% toward the goal's skill mix, from recent practice."""
    if not share:
        return 1.0
    weights = GOAL_SKILL_WEIGHTS.get(constraints.goal, {})
    skills = set(share) | set(weights) | {skill}
    total_w = sum(weights.get(s, 1.0) for s in skills)
    target = weights.get(skill, 1.0) / total_w
    actual = share.get(skill, 0.0)
    return max(0.8, min(1.2, 1.0 + 0.4 * (target - actual)))


# --- the engine -------------------------------------------------------------------


@dataclass
class _Context:
    snapshot: LearnerSnapshot
    config: PlannerConfig
    constraints: PlanConstraints
    estimates: LearnerEstimates
    memory: dict[str, MemoryState]
    share: dict[str, float]


def _sub_estimate(ctx: _Context, obj: CatalogObjective) -> SubskillEstimate:
    if ctx.config.predictive:
        return ctx.estimates.subskill(obj.skill, obj.subskill)
    # Ablation: the skill-level v2 estimate stands in for every objective.
    skill = ctx.estimates.skills.get(obj.skill)
    est = prior_subskill(skill, obj.skill, obj.subskill)
    if skill is not None and skill.ability is not None and skill.ability_se is not None:
        est.ability_se = skill.ability_se
        est.status = skill.status
        est.mastery = skill.mastery
        est.pattern = Pattern.STABLE
        est.independent_count = skill.independent_count
        est.event_ids = list(ctx.estimates.subskills.get((obj.skill, obj.subskill), est).event_ids)
    return est


def _decide_difficulty(
    ctx: _Context, obj: CatalogObjective, est: SubskillEstimate
) -> DifficultyDecision:
    if ctx.config.adaptive_difficulty:
        return choose_difficulty(
            est,
            objective_id=obj.objective_id,
            content_difficulty=obj.difficulty,
            linguistic_level=obj.cefr,
            previous_difficulty=ctx.snapshot.last_difficulty.get(obj.objective_id),
            target_success=ctx.config.target_success,
        )
    # Ablation: always the content's own level.
    neutral = SubskillEstimate(
        skill=est.skill,
        subskill=est.subskill,
        objective_id=est.objective_id,
        ability=est.ability,
        ability_se=est.ability_se,
        status=EvidenceStatus.INSUFFICIENT.value,
        pattern=est.pattern,
    )
    decision = choose_difficulty(
        neutral,
        objective_id=obj.objective_id,
        content_difficulty=obj.difficulty,
        linguistic_level=obj.cefr,
    )
    p, lo, hi = est.p_success(decision.task_difficulty)
    return DifficultyDecision(
        **{
            **decision.__dict__,
            "predicted_success": p,
            "predicted_low": lo,
            "predicted_high": hi,
            "status": est.status,
            "reason": "fixed difficulty at the content's level (adaptive difficulty off)",
        }
    )


def _prereq_state(ctx: _Context, obj: CatalogObjective) -> tuple[list[str], list[str]]:
    """(weak prerequisites, unmet-but-unassessed prerequisites)."""
    by_id = {o.objective_id: o for o in ctx.snapshot.catalog}
    weak, unknown = [], []
    for pre_id in obj.prerequisites:
        pre = by_id.get(pre_id)
        if pre is None:
            continue
        est = _sub_estimate(ctx, pre)
        if est.status == EvidenceStatus.INSUFFICIENT.value:
            unknown.append(pre_id)
        elif est.mastery_probability(pre.difficulty) < WEAK_PROBABILITY:
            weak.append(pre_id)
    return weak, unknown


def _scored(rec: Recommendation, ctx: _Context) -> Recommendation:
    weights = INTENT_WEIGHTS[rec.intent]
    total_w = sum(weights.values())
    raw = sum(weights[c] * _clip(rec.components.get(c, 0.0)) for c in COMPONENTS) / total_w
    rec.estimated_minutes = MINUTES.get(rec.activity, 5.0)
    balance = _balance_factor(rec.skill, ctx.share, ctx.constraints)
    fatigue = ctx.constraints.fatigue_penalty(rec.estimated_minutes)
    rec.components["balance_factor"] = balance
    rec.components["fatigue_factor"] = fatigue
    # The goal's skill weighting is already in the ``importance`` component.
    rec.score = raw * balance * fatigue
    return rec


def _grammar_candidates(ctx: _Context) -> list[Recommendation]:
    snap, cfg = ctx.snapshot, ctx.config
    out: list[Recommendation] = []
    target_level = _level_index(snap.target_cefr)
    catalog = [o for o in snap.catalog if o.skill == "grammar"]
    any_grammar_evidence = any(k[0] == "grammar" for k in ctx.estimates.subskills)
    frontier_open = True  # at most one introduction candidate (the first eligible)
    for obj in catalog:
        if "grammar" in ctx.constraints.avoid_skills:
            break
        est = _sub_estimate(ctx, obj)
        mem = ctx.memory.get(obj.objective_id)
        weak_pre, unknown_pre = _prereq_state(ctx, obj)
        importance = _importance("grammar", obj.cefr, ctx.constraints, snap.target_cefr)
        beyond_target = _level_index(obj.cefr) > target_level
        has_evidence = (obj.skill, obj.subskill) in ctx.estimates.subskills
        decision = _decide_difficulty(ctx, obj, est)
        p = decision.predicted_success
        m_prob = est.mastery_probability(obj.difficulty)
        ids = list(est.event_ids)
        pred = predict_success(
            ctx.estimates, "grammar", obj.subskill, decision.task_difficulty, as_of=snap.now_iso
        ).as_dict()
        if not cfg.predictive:
            pred["p_success"] = round(p, 4)
            pred["method"] = "lkm-evidence-v2 (skill level)"

        def rec(
            intent: str, activity: str, rationale: list[str], benefit: str, **comp: float
        ) -> Recommendation:
            return Recommendation(
                activity=activity,
                intent=intent,
                skill="grammar",
                target=obj.subskill,
                subskill=obj.subskill,
                objective_id=obj.objective_id,
                difficulty=decision,
                predicted_success=pred,
                rationale=rationale,
                expected_benefit=benefit,
                evidence=_evidence_summary(
                    ids,
                    mastery_probability=round(m_prob, 4),
                    retrievability=None
                    if mem is None or mem.retrievability is None
                    else round(mem.retrievability, 4),
                ),
                uncertainty=_uncertainty(est),
                components={
                    "importance": importance,
                    "relevance": 0.4 if beyond_target else 1.0,
                    **comp,
                },
                sources=["curriculum"],
            )

        # 1. Not enough evidence: assess (only content up to one level above target).
        if not has_evidence or est.status == EvidenceStatus.INSUFFICIENT.value:
            if _level_index(obj.cefr) <= target_level + 1 and not weak_pre:
                # Easier content first: its result also tells us about what builds on it.
                out.append(
                    rec(
                        "assessment",
                        "diagnostic_check",
                        [
                            f"no reliable evidence on {obj.subskill} yet "
                            f"({est.independent_count} observation(s))",
                            "a short graded check prevents guessing a level",
                        ],
                        "reduces uncertainty about this objective so later choices fit",
                        uncertainty=est.uncertainty,
                        coverage=(0.0 if has_evidence else 1.0)
                        * (1.0 - 0.1 * _level_index(obj.cefr)),
                        gain=0.3,
                        urgency=0.2 * len(unknown_pre),
                    )
                )
            continue
        # 2. A one-session dip: confirm before remediating.
        if est.pattern == Pattern.TEMPORARY_DIP:
            dip = rec(
                "assessment",
                "diagnostic_check",
                [
                    f"the last session on {obj.subskill} was weaker than before",
                    "one weak session may be a fluctuation: check before re-teaching",
                ],
                "distinguishes a temporary dip from a persistent decline",
                uncertainty=max(est.uncertainty, 0.8),
                coverage=0.0,
                gain=0.4,
                urgency=1.0,
            )
            # A confirmation check on an active objective is not a coverage
            # probe: it is exempt from the assessment cap.
            dip.evidence["check"] = "dip_confirmation"
            out.append(dip)
            continue
        # 3. A weak prerequisite: remediate the prerequisite, not this.
        if weak_pre:
            continue  # the prerequisite produces its own remediation candidate
        weak = (
            m_prob < WEAK_PROBABILITY
            and est.pattern
            in (
                Pattern.PERSISTENT_WEAKNESS,
                Pattern.PERSISTENT_DECLINE,
                Pattern.STABLE,
                Pattern.SINGLE_SESSION,
            )
            and (est.mastery or 0.0) < 0.5
        )
        dependents = [o.objective_id for o in catalog if obj.objective_id in o.prerequisites]
        if weak:
            reasons = [
                f"{obj.subskill} is a demonstrated weakness "
                f"(mastery {est.mastery or 0.0:.0%}, {est.status}, pattern {est.pattern})"
            ]
            if dependents:
                reasons.append(f"prerequisite of {', '.join(dependents)}")
            out.append(
                rec(
                    "remediation",
                    "grammar_practice",
                    reasons + [decision.reason],
                    "targets a demonstrated weakness at a difficulty the learner can succeed at",
                    # Remediation re-teaches with support: its value does not
                    # vanish when even the easiest task is hard for now.
                    gain=(1.0 - m_prob) * (0.5 + 0.5 * _zone(p, cfg.target_success)),
                    success=p,
                    urgency=min(
                        1.0,
                        (0.9 if est.pattern in PERSISTENT else 0.6) + 0.2 * len(dependents),
                    ),
                    difficulty_fit=1.0 - min(1.0, abs(p - cfg.target_success) / 0.5),
                )
            )
            continue
        # 4. Mastered: no practice without a retention reason.
        mastered = m_prob >= MASTERED_PROBABILITY
        if mastered:
            if cfg.fsrs_integration and mem is not None and mem.needs_review:
                r = mem.retrievability or 0.0
                out.append(
                    rec(
                        "review",
                        "retention_review",
                        [
                            f"{obj.subskill} was mastered but recall has decayed "
                            f"(FSRS retrievability {r:.0%})",
                        ],
                        "a timely retrieval keeps a mastered construction from being forgotten",
                        retention=1.0 - r,
                        urgency=_clip((REVIEW_THRESHOLD - r) / REVIEW_THRESHOLD + 0.3),
                        gain=0.5 * (1.0 - r),
                        success=p,
                        difficulty_fit=0.7,
                    )
                )
            elif decision.task_tier != "stretch" and decision.bounded_by != "content_window_high":
                out.append(
                    rec(
                        "progression",
                        "grammar_practice",
                        [
                            f"{obj.subskill} is mastered at its current difficulty "
                            f"({m_prob:.0%} posterior)",
                            "a more demanding task keeps it in the learning zone",
                            decision.reason,
                        ],
                        "extends a mastered construction to harder use",
                        gain=0.6 * _zone(p, cfg.target_success),
                        success=p,
                        progression=0.6,
                        difficulty_fit=1.0 - min(1.0, abs(p - cfg.target_success) / 0.5),
                    )
                )
            continue
        # 5. In progress: reinforce in the success zone.
        out.append(
            rec(
                "reinforcement",
                "grammar_practice",
                [
                    f"{obj.subskill} is in progress (mastery probability {m_prob:.0%})",
                    decision.reason,
                ],
                "practice in the optimal-challenge zone consolidates the construction",
                gain=(1.0 - m_prob) * _zone(p, cfg.target_success),
                success=p,
                uncertainty=est.uncertainty,
                retention=0.0
                if mem is None or mem.retrievability is None
                else 1.0 - mem.retrievability,
                difficulty_fit=1.0 - min(1.0, abs(p - cfg.target_success) / 0.5),
                urgency=0.3 if est.pattern == Pattern.PERSISTENT_WEAKNESS else 0.1,
            )
        )
    # 6. Introduce the next construction whose prerequisites are mastered.
    for obj in catalog:
        if not frontier_open or "grammar" in ctx.constraints.avoid_skills:
            break
        if (obj.skill, obj.subskill) in ctx.estimates.subskills:
            continue
        if _level_index(obj.cefr) > target_level:
            continue
        prereqs_ok = all(
            _sub_estimate(ctx, o).mastery_probability(o.difficulty) >= 0.5
            for o in ctx.snapshot.catalog
            if o.objective_id in obj.prerequisites
        )
        if not prereqs_ok or not any_grammar_evidence:
            continue
        est = _sub_estimate(ctx, obj)
        decision = _decide_difficulty(ctx, obj, est)
        out.append(
            Recommendation(
                activity="grammar_practice",
                intent="introduction",
                skill="grammar",
                target=obj.subskill,
                subskill=obj.subskill,
                objective_id=obj.objective_id,
                difficulty=decision,
                predicted_success=predict_success(
                    ctx.estimates,
                    "grammar",
                    obj.subskill,
                    decision.task_difficulty,
                    as_of=snap.now_iso,
                ).as_dict(),
                rationale=[
                    f"next construction on the path ({obj.cefr})",
                    "its prerequisites are in place" if obj.prerequisites else "no prerequisites",
                ],
                expected_benefit="new content at the edge of current ability",
                evidence=_evidence_summary([], prerequisites=list(obj.prerequisites)),
                uncertainty=_uncertainty(est),
                components={
                    "gain": 0.8,
                    "success": decision.predicted_success,
                    "importance": _importance(
                        "grammar", obj.cefr, ctx.constraints, snap.target_cefr
                    ),
                    "relevance": 1.0,
                    "coverage": 1.0,
                    "progression": 1.0,
                    "difficulty_fit": 0.6,
                },
                sources=["curriculum"],
            )
        )
        frontier_open = False
    return out


def _vocabulary_candidates(ctx: _Context) -> list[Recommendation]:
    snap, cfg = ctx.snapshot, ctx.config
    if "vocabulary" in ctx.constraints.avoid_skills:
        return []
    out: list[Recommendation] = []
    now = snap.now
    due_rank = 0
    vocab = sorted(
        snap.vocabulary, key=lambda v: (str(v.get("next_review") or "9999"), str(v.get("word")))
    )

    def due_at_of(v: dict[str, Any]) -> datetime | None:
        return _parse(v["next_review"]) if v.get("next_review") else None

    due_total = sum(1 for v in vocab if (d := due_at_of(v)) is not None and d <= now)
    active = 0
    for item in vocab:
        word = str(item.get("word") or "")
        if not word:
            continue
        mem = ctx.memory.get(f"vocabulary:{word.strip().lower()}")
        due_at = due_at_of(item)
        is_due = due_at is not None and due_at <= now
        r_live = live_retrievability(item.get("card_state"), now)
        demonstrated = mem is not None and mem.demonstrated
        if not demonstrated or (r_live is not None and r_live < 0.9):
            active += 1
        objective = f"vocabulary.{word}"
        evidence = _evidence_summary(
            [] if mem is None else list(mem.event_ids),
            retrievability=None if r_live is None else round(r_live, 4),
            exposures=0 if mem is None else mem.exposures,
            recognition_successes=0 if mem is None else mem.recognition_successes,
            production_successes=0 if mem is None else mem.production_successes,
        )
        if cfg.fsrs_integration and mem is not None and mem.leech:
            out.append(
                Recommendation(
                    activity="vocabulary_remediation",
                    intent="remediation",
                    skill="vocabulary",
                    target=word,
                    subskill="production",
                    objective_id=objective,
                    rationale=[
                        f"'{word}' failed {mem.consecutive_failures} retrievals in a row "
                        f"({mem.lapses} lapse(s)): re-drilling the same card is not working",
                        "re-teach it in context, contrasted with what it gets confused with",
                    ],
                    expected_benefit="breaks a repeated-failure loop that plain review repeats",
                    evidence=evidence,
                    uncertainty={"status": "leech"},
                    components={
                        "gain": 0.8,
                        "success": 0.5,
                        "urgency": 1.0,
                        "importance": 0.7,
                        "relevance": 1.0,
                        "difficulty_fit": 0.6,
                    },
                    sources=["fsrs", "curriculum"],
                )
            )
            continue
        if not is_due:
            continue
        if cfg.fsrs_integration:
            r = r_live if r_live is not None else 0.0
            # Recognition first; production once recognition is demonstrated.
            mode = (
                "production" if mem is not None and mem.recognition_successes > 0 else "recognition"
            )
            never_recalled = mem is None or mem.reviews == 0
            # A card never reviewed has no memory estimate yet: moderate need.
            retention = 1.0 - r if r_live is not None else 0.7
            overdue_days = max(0.0, (now - due_at).total_seconds() / 86400.0) if due_at else 0.0
            urgency = _clip(0.4 + 0.15 * overdue_days + 0.4 * retention)
            reasons = [
                f"'{word}' is due (FSRS)"
                + ("" if r_live is None else f", predicted recall {r:.0%}")
            ]
            if never_recalled:
                reasons.append("seen in conversation but never recalled: exposure is not recall")
            if mode == "production":
                reasons.append("recognised before: now ask for independent production")
        else:
            mode = "recognition"
            retention = 0.5
            urgency = max(0.3, 1.0 - due_rank / max(due_total, 1))
            reasons = [f"'{word}' is due for review (FSRS)"]
        due_rank += 1
        out.append(
            Recommendation(
                activity="vocabulary_review",
                intent="review",
                skill="vocabulary",
                target=word,
                subskill=mode,
                objective_id=objective,
                mode=mode,
                rationale=reasons,
                expected_benefit="retrieval at the scheduled time strengthens long-term memory",
                evidence=evidence,
                uncertainty={"status": "fsrs", "retrievability_known": r_live is not None},
                components={
                    "retention": retention,
                    "urgency": urgency,
                    "gain": 0.6,
                    "success": 0.7 if mode == "recognition" else 0.55,
                    "importance": _importance(
                        "vocabulary", None, ctx.constraints, snap.target_cefr
                    ),
                    "relevance": 1.0,
                    "difficulty_fit": 0.7,
                },
                sources=["fsrs"],
            )
        )
    if snap.new_words and active < MIN_ACTIVE_WORDS:
        out.append(
            Recommendation(
                activity="vocabulary_expansion",
                intent="introduction",
                skill="vocabulary",
                target=",".join(snap.new_words[:3]),
                objective_id="vocabulary.expansion",
                rationale=[
                    f"only {active} word(s) currently in learning (< {MIN_ACTIVE_WORDS})",
                    "add a few new words while the review load is light",
                ],
                expected_benefit="grows vocabulary without overloading reviews",
                evidence={"active_words": active},
                uncertainty={},
                components={
                    "gain": 0.8,
                    "progression": 1.0,
                    "relevance": 1.0,
                    "coverage": 1.0,
                    "importance": _importance(
                        "vocabulary", None, ctx.constraints, snap.target_cefr
                    ),
                    "success": 0.7,
                    "difficulty_fit": 0.6,
                },
                sources=["curriculum"],
            )
        )
    return out


def _skill_candidates(ctx: _Context) -> list[Recommendation]:
    out: list[Recommendation] = []
    for skill, activity in _SKILL_ACTIVITY.items():
        if skill in ctx.constraints.avoid_skills or skill == "speaking":
            continue
        est = ctx.estimates.skills.get(skill)
        if est is None or est.mastery is None or status_rank(est.status) == 0:
            if skill not in GOAL_SKILL_WEIGHTS.get(ctx.constraints.goal, {}):
                continue
            out.append(
                Recommendation(
                    activity=activity,
                    intent="assessment",
                    skill=skill,
                    target=skill,
                    rationale=[f"no graded evidence for {skill} yet, and the goal weights it"],
                    expected_benefit=f"a first measurement of {skill}",
                    evidence=_evidence_summary([] if est is None else est.event_ids),
                    uncertainty={"status": EvidenceStatus.INSUFFICIENT.value},
                    components={
                        "uncertainty": 1.0,
                        "coverage": 1.0,
                        "importance": _importance(
                            skill, None, ctx.constraints, ctx.snapshot.target_cefr
                        ),
                        "relevance": 0.6,
                    },
                    sources=["curriculum"],
                )
            )
            continue
        m = est.mastery
        intent = "remediation" if m < 0.4 else "reinforcement"
        out.append(
            Recommendation(
                activity=activity,
                intent=intent,
                skill=skill,
                target=skill,
                rationale=[f"{skill} mastery {m:.0%} on {est.status} evidence"],
                expected_benefit=f"develops {skill}",
                evidence=_evidence_summary(est.event_ids),
                uncertainty={"status": est.status, "uncertainty": round(est.uncertainty, 4)},
                components={
                    "gain": (1.0 - m) * _zone(m, ctx.config.target_success),
                    "urgency": 0.6 if intent == "remediation" else 0.2,
                    "importance": _importance(
                        skill, None, ctx.constraints, ctx.snapshot.target_cefr
                    ),
                    "relevance": 0.7,
                    "success": m,
                    "difficulty_fit": 0.5,
                },
                sources=["curriculum"],
            )
        )
    return out


def _conversation_candidate(ctx: _Context) -> Recommendation:
    """Contextual conversation: transfer of what is mastered, always available."""
    mastered = [
        sub
        for (skill, sub), est in sorted(ctx.estimates.subskills.items())
        if skill == "grammar" and est.mastery is not None and est.mastery >= 0.6
    ]
    speaking = ctx.estimates.skills.get("speaking") or ctx.estimates.skills.get("pragmatics")
    return Recommendation(
        activity="conversation_practice",
        intent="reinforcement",
        skill="speaking",
        target="conversation",
        rationale=[
            "contextual practice transfers constructions to real use",
            *([f"uses {', '.join(mastered[:3])} in context"] if mastered else []),
        ],
        expected_benefit="transfer and fluency; also yields fresh evidence on many skills",
        evidence={"practised_constructions": mastered[:5]},
        uncertainty={},
        components={
            "gain": 0.35,
            "success": 0.7,
            "importance": _importance("speaking", None, ctx.constraints, ctx.snapshot.target_cefr),
            "relevance": 0.6,
            "difficulty_fit": 0.5,
            "uncertainty": 0.3 if speaking is None else speaking.uncertainty * 0.5,
            "urgency": 0.1,
        },
        sources=["curriculum"],
    )


def _dedupe(cands: list[Recommendation]) -> list[Recommendation]:
    """One recommendation per key; FSRS reviews win, keeping both reasons."""
    best: dict[str, Recommendation] = {}
    for rec in cands:
        cur = best.get(rec.key)
        if cur is None:
            best[rec.key] = rec
            continue
        winner, loser = (cur, rec) if _rank(cur) <= _rank(rec) else (rec, cur)
        if "fsrs" in loser.sources and "fsrs" not in winner.sources and loser.intent == "review":
            winner, loser = loser, winner
        winner.rationale.append(f"(also proposed as {loser.intent}: {loser.rationale[0]})")
        winner.sources = sorted(set(winner.sources) | set(loser.sources))
        best[rec.key] = winner
    return list(best.values())


def _rank(rec: Recommendation) -> tuple[float, int, str]:
    return (-rec.score, INTENT_ORDER.index(rec.intent), rec.key)


def plan(
    snapshot: LearnerSnapshot,
    *,
    constraints: PlanConstraints | None = None,
    config: PlannerConfig | None = None,
    model: SubskillModel | None = None,
) -> Plan:
    """Rank and select the next-best learning activities for a snapshot."""
    constraints = constraints or PlanConstraints()
    config = config or PlannerConfig()
    estimates = (model or SubskillModel()).estimate(snapshot.evidence)
    memory = replay_memory(snapshot.evidence, snapshot.now)
    ctx = _Context(snapshot, config, constraints, estimates, memory, _recent_share(snapshot))

    cands = _grammar_candidates(ctx) + _vocabulary_candidates(ctx) + _skill_candidates(ctx)
    cands.append(_conversation_candidate(ctx))
    cands = [_scored(c, ctx) for c in cands]
    considered = len(cands)
    cands = _dedupe(cands)
    cands.sort(key=_rank)

    chosen: list[Recommendation] = []
    deferred: list[dict[str, Any]] = []
    remaining = constraints.time_available_minutes
    counts = {"assessment": 0, "introduction": 0}
    assessment_minutes = 0.0
    assessment_budget = MAX_ASSESSMENT_SHARE * constraints.time_available_minutes
    for rec in cands:
        if len(chosen) >= constraints.max_actions:
            deferred.append({"key": rec.key, "intent": rec.intent, "why": "max_actions"})
            continue
        capped = rec.intent == "assessment" and rec.evidence.get("check") != "dip_confirmation"
        if capped and counts["assessment"] >= MAX_ASSESSMENTS:
            deferred.append({"key": rec.key, "intent": rec.intent, "why": "assessment_cap"})
            continue
        if capped and assessment_minutes + rec.estimated_minutes > assessment_budget:
            deferred.append({"key": rec.key, "intent": rec.intent, "why": "assessment_time_share"})
            continue
        if rec.intent == "introduction" and counts["introduction"] >= MAX_INTRODUCTIONS:
            deferred.append({"key": rec.key, "intent": rec.intent, "why": "introduction_cap"})
            continue
        if rec.estimated_minutes > remaining and chosen:
            deferred.append({"key": rec.key, "intent": rec.intent, "why": "time_budget"})
            continue
        chosen.append(rec)
        remaining -= rec.estimated_minutes
        if rec.intent == "introduction" or capped:
            counts[rec.intent] += 1
        if capped:
            assessment_minutes += rec.estimated_minutes
    return Plan(
        engine=ENGINE,
        user_id=snapshot.user_id,
        language=snapshot.language,
        generated_at=snapshot.now_iso,
        input_digest=snapshot.digest(),
        config={
            "predictive": config.predictive,
            "adaptive_difficulty": config.adaptive_difficulty,
            "fsrs_integration": config.fsrs_integration,
            "target_success": config.target_success,
            "goal": constraints.goal,
            "minutes": constraints.time_available_minutes,
        },
        recommendations=chosen,
        considered=considered,
        deferred=deferred,
    )
