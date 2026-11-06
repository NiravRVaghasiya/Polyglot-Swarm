"""The Next Best Learning Action planner.

Reads the learner model's evidence-derived skill estimates (mastery,
uncertainty, evidence quality, coverage — ADR-0031), FSRS-due reviews, and
recurring grammar errors, and produces a ranked list of
:class:`LearningAction`\\s that maximizes value subject to the plan constraints.

Every action carries an :class:`ActionIntent`:

- **assessment** when a skill has ``insufficient_evidence`` (or a grammar
  error was seen only once): gather evidence instead of assuming weakness.
  Assessments are scored by *information* value
  (:func:`~src.curriculum.objectives.assessment_value`), never by a guessed
  mastery, and at most :data:`MAX_ASSESSMENT_ACTIONS` are planned so a thin
  model does not crowd out learning;
- **remediation** when the evidence (provisional or better) shows a
  weakness, or an error recurs;
- **reinforcement** in the optimal-challenge zone, and for every FSRS-due
  review (FSRS still decides *when*; its scheduling is untouched);
- **advancement** when the evidence shows strength with a tight interval.

Readiness treats a prerequisite as blocking only when the evidence shows it is
weak; an unassessed prerequisite does not block.

Pure over its inputs and deterministic: it queries the belief stores but calls
no LLM, so a plan is fast, reproducible, and fully explainable.
"""

from __future__ import annotations

from src.curriculum.actions import ActionIntent, ActionType, LearningAction, estimated_minutes
from src.curriculum.constraints import PlanConstraints
from src.curriculum.objectives import (
    assessment_value,
    expected_learning_value,
    review_urgency,
    weakness_urgency,
)
from src.learner import get_knowledge_model, skill_graph
from src.learner.estimation import SkillEstimate, status_rank
from src.llm.schemas import GrammarItem
from src.memory import analytics, vocabulary_db

# How many due items / weaknesses to consider as candidates.
_MAX_REVIEW_CANDIDATES = 10
_MAX_GRAMMAR_CANDIDATES = 5
#: At most this many evidence-gathering actions per plan.
MAX_ASSESSMENT_ACTIONS = 2

#: Mastery below this (with at least provisional evidence) is a weakness.
WEAK_MASTERY = 0.4
#: Mastery at or above this, with the interval's lower bound at or above
#: ``ADVANCE_LOWER_BOUND``, is strength worth advancing from.
STRONG_MASTERY = 0.75
ADVANCE_LOWER_BOUND = 0.5
#: The mastery value an *unknown* belief enters ELV with: the neutral
#: midpoint, never zero.
NEUTRAL_MASTERY = 0.5

# Map a skill to the action type that best develops (or probes) it.
_SKILL_ACTION: dict[str, ActionType] = {
    "speaking": ActionType.CONTINUE_CONVERSATION,
    "listening": ActionType.LISTENING_CHECK,
    "reading": ActionType.READING,
    "writing": ActionType.WRITING_EXERCISE,
    "pragmatics": ActionType.CONTINUE_CONVERSATION,
    "vocabulary": ActionType.RETRIEVAL_PRACTICE,
}


def classify_skill(estimate: SkillEstimate | None) -> ActionIntent:
    """Choose the intent for a skill from its evidence."""
    if estimate is None or estimate.mastery is None or status_rank(estimate.status) == 0:
        return ActionIntent.ASSESSMENT
    if estimate.mastery < WEAK_MASTERY:
        return ActionIntent.REMEDIATION
    if estimate.mastery >= STRONG_MASTERY and (estimate.mastery_low or 0.0) >= ADVANCE_LOWER_BOUND:
        return ActionIntent.ADVANCEMENT
    return ActionIntent.REINFORCEMENT


def _blocking_prerequisites(skill: str, estimates: dict[str, SkillEstimate]) -> list[str]:
    """Prerequisites the evidence shows are weak (unassessed ones never block)."""
    blocking = []
    for prereq in skill_graph.skill_prerequisites(skill):
        e = estimates.get(prereq)
        if e is not None and e.mastery is not None and status_rank(e.status) >= 1:
            if e.mastery < WEAK_MASTERY:
                blocking.append(prereq)
    return blocking


def _coverage_gap(estimate: SkillEstimate | None) -> float:
    if estimate is None:
        return 1.0
    fraction = estimate.coverage.catalog_assessed_fraction()
    return 1.0 if fraction is None else 1.0 - fraction


def _review_actions(
    user_id: str,
    language: str,
    constraints: PlanConstraints,
) -> list[LearningAction]:
    """Candidate review actions from FSRS-due vocabulary (WHEN comes from FSRS)."""
    due = vocabulary_db.get_due(user_id, language, limit=_MAX_REVIEW_CANDIDATES)
    actions: list[LearningAction] = []
    for rank, item in enumerate(due):
        word = item.get("word", "")
        if not word:
            continue
        # A due word's "mastery" for scoring is its recognition dimension.
        mastery = float(item.get("recognition") or 0.0)
        urgency = review_urgency(rank, len(due))
        priority = expected_learning_value(
            mastery=mastery,
            uncertainty=0.4,
            urgency=urgency,
            skill="vocabulary",
            estimated_minutes=estimated_minutes(ActionType.REVIEW_VOCAB),
            constraints=constraints,
        )
        actions.append(
            LearningAction(
                type=ActionType.REVIEW_VOCAB,
                target=word,
                skill="vocabulary",
                reason=f"'{word}' is due for review (FSRS)",
                priority=priority,
                payload={"item": item},
                intent=ActionIntent.REINFORCEMENT.value,
            )
        )
    return actions


def _grammar_actions(
    user_id: str,
    language: str,
    constraints: PlanConstraints,
    estimates: dict[str, SkillEstimate],
) -> list[LearningAction]:
    """Candidate grammar actions from recurring errors and unassessed constructions."""
    grammar = estimates.get("grammar")
    grammar_mastery = NEUTRAL_MASTERY
    if grammar is not None and grammar.mastery is not None:
        grammar_mastery = grammar.mastery
    grammar_uncertainty = grammar.uncertainty if grammar is not None else 1.0

    actions: list[LearningAction] = []
    patterns = analytics.get_error_patterns(user_id, language, include_mastered=False)
    patterns = patterns[:_MAX_GRAMMAR_CANDIDATES]
    max_occ = max((p["occurrences"] for p in patterns), default=0)
    for p in patterns:
        construction = p["error_type"]
        occurrences = int(p["occurrences"])
        urgency = weakness_urgency(occurrences, max_occ)
        priority = expected_learning_value(
            mastery=grammar_mastery,
            uncertainty=grammar_uncertainty,
            urgency=urgency,
            skill="grammar",
            estimated_minutes=estimated_minutes(ActionType.TARGET_GRAMMAR),
            constraints=constraints,
        )
        prereqs = skill_graph.construction_prerequisites(language, construction)
        # A confusable pair is better served by contrasting the two forms.
        action_type = (
            ActionType.CONTRAST_TWO_FORMS if "_vs_" in construction else ActionType.TARGET_GRAMMAR
        )
        if occurrences >= 2:
            intent = ActionIntent.REMEDIATION
            reason = f"'{construction}' recurs ({occurrences}x) — a demonstrated weakness"
        else:
            intent = ActionIntent.ASSESSMENT
            reason = f"'{construction}' was flagged once — check it before drilling it"
        actions.append(
            LearningAction(
                type=action_type,
                target=construction,
                skill="grammar",
                reason=reason,
                priority=priority,
                payload={"occurrences": occurrences, "prerequisites": prereqs},
                intent=intent.value,
            )
        )

    # Coverage: when grammar evidence is thin, probe a construction never assessed.
    flagged = {p["error_type"] for p in patterns}
    if (
        classify_skill(grammar) == ActionIntent.ASSESSMENT
        and "grammar" not in constraints.avoid_skills
    ):
        catalog = [f"grammar.{c.construction}" for c in _pack_constructions(language)]
        unassessed = grammar.coverage.unassessed_objectives if grammar is not None else catalog
        candidates = [o.split(".", 1)[1] for o in unassessed if o.split(".", 1)[1] not in flagged]
        if candidates:
            target = candidates[0]  # easiest unassessed first (deterministic)
            actions.append(
                LearningAction(
                    type=ActionType.DIAGNOSTIC_CHECK,
                    target=target,
                    skill="grammar",
                    reason=f"no evidence on '{target}' yet — a short check to find your level",
                    priority=assessment_value(
                        uncertainty=grammar_uncertainty,
                        evidence_quality=grammar.quality.score() if grammar is not None else 0.0,
                        coverage_gap=_coverage_gap(grammar),
                        skill="grammar",
                        estimated_minutes=estimated_minutes(ActionType.DIAGNOSTIC_CHECK),
                        constraints=constraints,
                    ),
                    payload={"objective_id": f"grammar.{target}"},
                    intent=ActionIntent.ASSESSMENT.value,
                )
            )

    # Assessed grammar with no recorded error patterns (e.g. evidence from a
    # task other than conversation analysis) still gets an evidence-driven
    # action: its struggling objectives when known, else the skill itself.
    intent = classify_skill(grammar)
    if (
        not patterns
        and grammar is not None
        and grammar.mastery is not None
        and intent != ActionIntent.ASSESSMENT
        and "grammar" not in constraints.avoid_skills
    ):
        struggling = [o.split(".", 1)[1] for o in grammar.coverage.struggling_objective_ids]
        targets = (
            struggling[:2] if intent == ActionIntent.REMEDIATION and struggling else ["grammar"]
        )
        for target in targets:
            actions.append(
                LearningAction(
                    type=ActionType.TARGET_GRAMMAR,
                    target=target,
                    skill="grammar",
                    reason=_skill_reason("grammar", intent, grammar),
                    priority=expected_learning_value(
                        mastery=grammar.mastery,
                        uncertainty=grammar.uncertainty,
                        urgency=0.6 if intent == ActionIntent.REMEDIATION else 0.4,
                        skill="grammar",
                        estimated_minutes=estimated_minutes(ActionType.TARGET_GRAMMAR),
                        constraints=constraints,
                    ),
                    payload={"status": grammar.status},
                    intent=intent.value,
                )
            )
    return actions


def _pack_constructions(language: str) -> list[GrammarItem]:
    try:
        from src.languages import list_constructions

        return sorted(list_constructions(language), key=lambda c: (c.cefr, c.construction))
    except Exception:  # noqa: BLE001 - no pack, no catalog
        return []


def _skill_actions(
    constraints: PlanConstraints,
    estimates: dict[str, SkillEstimate],
    *,
    reviews_due: bool = False,
) -> list[LearningAction]:
    """One candidate per skill, with its intent chosen from the evidence.

    With FSRS reviews due, no separate vocabulary *assessment* is proposed:
    a graded review already is vocabulary evidence.
    """
    actions: list[LearningAction] = []
    for skill, action_type in _SKILL_ACTION.items():
        if skill in constraints.avoid_skills:
            continue
        if (
            skill == "vocabulary"
            and reviews_due
            and classify_skill(estimates.get(skill)) == ActionIntent.ASSESSMENT
        ):
            continue
        blocking = _blocking_prerequisites(skill, estimates)
        if blocking:
            continue  # remediate the weak prerequisite first (it gets its own action)
        e = estimates.get(skill)
        intent = classify_skill(e)
        minutes = estimated_minutes(action_type)
        if intent == ActionIntent.ASSESSMENT:
            priority = assessment_value(
                uncertainty=e.uncertainty if e is not None else 1.0,
                evidence_quality=e.quality.score() if e is not None else 0.0,
                coverage_gap=_coverage_gap(e),
                skill=skill,
                estimated_minutes=minutes,
                constraints=constraints,
            )
        else:
            assert e is not None and e.mastery is not None
            priority = expected_learning_value(
                mastery=e.mastery,
                uncertainty=e.uncertainty,
                urgency=0.6 if intent == ActionIntent.REMEDIATION else 0.4,
                skill=skill,
                estimated_minutes=minutes,
                constraints=constraints,
            )
        actions.append(
            LearningAction(
                type=action_type,
                target=skill,
                skill=skill,
                reason=_skill_reason(skill, intent, e),
                priority=priority,
                payload={"status": e.status if e is not None else "insufficient_evidence"},
                intent=intent.value,
            )
        )
    return actions


def _skill_reason(skill: str, intent: ActionIntent, e: SkillEstimate | None) -> str:
    if intent == ActionIntent.ASSESSMENT:
        if e is None or e.mastery is None:
            return f"no graded evidence for {skill} yet — practise it so the model can assess it"
        return (
            f"too little evidence on {skill} to judge ({e.independent_count} independent "
            f"observation(s)) — gather more before deciding"
        )
    assert e is not None and e.mastery is not None
    if intent == ActionIntent.REMEDIATION:
        return f"{skill} is a weakness on {e.status} evidence (mastery {e.mastery:.0%})"
    if intent == ActionIntent.ADVANCEMENT:
        return f"{skill} looks strong (mastery {e.mastery:.0%}) — try harder material"
    return f"strengthen {skill} in the optimal-challenge zone (mastery {e.mastery:.0%})"


def plan_next_actions(
    user_id: str,
    language: str,
    *,
    constraints: PlanConstraints | None = None,
) -> list[LearningAction]:
    """Return a ranked, budget-fitting plan of next best learning actions.

    Candidates are drawn from due reviews (FSRS), grammar errors and coverage,
    and per-skill evidence, scored, ranked, and packed into the time budget
    with at most :data:`MAX_ASSESSMENT_ACTIONS` assessments. Always includes a
    conversation so a brand-new learner still gets a sensible next step.
    """
    constraints = constraints or PlanConstraints()
    estimates = get_knowledge_model().current_estimates(user_id, language)

    candidates: list[LearningAction] = []
    reviews = _review_actions(user_id, language, constraints)
    candidates += reviews
    candidates += _grammar_actions(user_id, language, constraints, estimates)
    candidates += _skill_actions(constraints, estimates, reviews_due=bool(reviews))

    # Fallback: a conversation is always a valid next action.
    if not any(a.type == ActionType.CONTINUE_CONVERSATION for a in candidates):
        speaking = estimates.get("speaking")
        speaking_mastery = (
            speaking.mastery if speaking is not None and speaking.mastery is not None else 0.3
        )
        candidates.append(
            LearningAction(
                type=ActionType.CONTINUE_CONVERSATION,
                target="conversation",
                skill="speaking",
                reason="a natural conversation exercises many skills at once",
                priority=expected_learning_value(
                    mastery=speaking_mastery,
                    uncertainty=speaking.uncertainty if speaking is not None else 1.0,
                    urgency=0.3,
                    skill="speaking",
                    estimated_minutes=estimated_minutes(ActionType.CONTINUE_CONVERSATION),
                    constraints=constraints,
                ),
                intent=classify_skill(speaking).value,
            )
        )

    # Rank by priority (desc; stable, so ties keep candidate order), then pack.
    candidates.sort(key=lambda a: a.priority, reverse=True)

    plan: list[LearningAction] = []
    remaining = constraints.time_available_minutes
    assessments = 0
    deferred: list[LearningAction] = []
    for action in candidates:
        if len(plan) >= constraints.max_actions:
            break
        is_assessment = action.intent == ActionIntent.ASSESSMENT.value
        if is_assessment and assessments >= MAX_ASSESSMENT_ACTIONS:
            deferred.append(action)
            continue
        if action.estimated_minutes <= remaining or not plan:
            plan.append(action)
            remaining -= action.estimated_minutes
            assessments += int(is_assessment)
    # The cap prefers learning over probing; it never leaves time unused.
    for action in deferred:
        if len(plan) >= constraints.max_actions:
            break
        if action.estimated_minutes <= remaining:
            plan.append(action)
            remaining -= action.estimated_minutes
    plan.sort(key=lambda a: a.priority, reverse=True)
    return plan


def plan_next_best(
    user_id: str,
    language: str,
    *,
    constraints: PlanConstraints | None = None,
) -> LearningAction | None:
    """Return just the single highest-value next action, or ``None`` if none."""
    plan = plan_next_actions(user_id, language, constraints=constraints)
    return plan[0] if plan else None
