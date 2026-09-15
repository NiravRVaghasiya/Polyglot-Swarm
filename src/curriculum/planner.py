"""The Next Best Learning Action planner.

Reads the learner's belief state (skill mastery + uncertainty, due reviews,
grammar weaknesses) and produces a ranked list of :class:`LearningAction`s that
maximizes Expected Learning Value subject to the plan constraints.

Pure over its inputs and deterministic: it queries the belief stores but calls
no LLM, so a plan is fast, reproducible, and fully explainable. It embodies the
WHAT/WHEN split — the planner chooses *what* to practise; FSRS (via
``vocabulary_db.get_due``) supplies *when* an item is due.
"""

from __future__ import annotations

from src.curriculum.actions import ActionType, LearningAction, estimated_minutes
from src.curriculum.constraints import PlanConstraints
from src.curriculum.objectives import (
    expected_learning_value,
    review_urgency,
    weakness_urgency,
)
from src.learner import get_knowledge_model, skill_graph
from src.learner.mastery_engine import SkillBelief
from src.memory import analytics, vocabulary_db

# How many due items / weaknesses to consider as candidates.
_MAX_REVIEW_CANDIDATES = 10
_MAX_GRAMMAR_CANDIDATES = 5


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
            )
        )
    return actions


def _grammar_actions(
    user_id: str,
    language: str,
    constraints: PlanConstraints,
    mastery_by_skill: dict[str, float],
) -> list[LearningAction]:
    """Candidate grammar actions from the learner's top error patterns."""
    patterns = analytics.get_error_patterns(user_id, language, include_mastered=False)
    patterns = patterns[:_MAX_GRAMMAR_CANDIDATES]
    if not patterns:
        return []
    max_occ = max(p["occurrences"] for p in patterns)
    grammar_mastery = mastery_by_skill.get("grammar", 0.0)
    grammar_uncertainty = 0.5

    actions: list[LearningAction] = []
    for p in patterns:
        construction = p["error_type"]
        urgency = weakness_urgency(p["occurrences"], max_occ)
        priority = expected_learning_value(
            mastery=grammar_mastery,
            uncertainty=grammar_uncertainty,
            urgency=urgency,
            skill="grammar",
            estimated_minutes=estimated_minutes(ActionType.TARGET_GRAMMAR),
            constraints=constraints,
        )
        # A construction with unmet prerequisites is better served by contrasting
        # the two confusable forms than by drilling it head-on.
        prereqs = skill_graph.construction_prerequisites(language, construction)
        action_type = (
            ActionType.CONTRAST_TWO_FORMS if "_vs_" in construction else (ActionType.TARGET_GRAMMAR)
        )
        actions.append(
            LearningAction(
                type=action_type,
                target=construction,
                skill="grammar",
                reason=(f"'{construction}' recurs ({p['occurrences']}x) — a top weakness"),
                priority=priority,
                payload={"occurrences": p["occurrences"], "prerequisites": prereqs},
            )
        )
    return actions


def _skill_practice_actions(
    constraints: PlanConstraints,
    beliefs: dict[str, SkillBelief],
    mastery_by_skill: dict[str, float],
) -> list[LearningAction]:
    """Candidate actions to practise weak-but-ready skills (skill balance)."""
    # Map a skill to the action type that best develops it.
    skill_action: dict[str, ActionType] = {
        "speaking": ActionType.CONTINUE_CONVERSATION,
        "listening": ActionType.LISTENING_CHECK,
        "reading": ActionType.READING,
        "writing": ActionType.WRITING_EXERCISE,
        "pragmatics": ActionType.CONTINUE_CONVERSATION,
        "vocabulary": ActionType.RETRIEVAL_PRACTICE,
    }
    actions: list[LearningAction] = []
    for skill, action_type in skill_action.items():
        if skill in constraints.avoid_skills:
            continue
        # Only propose skills the learner is ready for (prerequisites met).
        if not skill_graph.is_ready(skill, mastery_by_skill):
            continue
        belief = beliefs.get(skill)
        mastery = belief.mastery if belief else mastery_by_skill.get(skill, 0.0)
        unc = belief.uncertainty if belief else 1.0
        priority = expected_learning_value(
            mastery=mastery,
            uncertainty=unc,
            urgency=0.4,
            skill=skill,
            estimated_minutes=estimated_minutes(action_type),
            constraints=constraints,
        )
        actions.append(
            LearningAction(
                type=action_type,
                target=skill,
                skill=skill,
                reason=_skill_reason(skill, mastery, unc),
                priority=priority,
            )
        )
    return actions


def _skill_reason(skill: str, mastery: float, uncertainty: float) -> str:
    if uncertainty > 0.7:
        return f"little evidence yet for {skill} — practise to calibrate the model"
    if mastery < 0.4:
        return f"{skill} is a current weakness (mastery {mastery:.0%})"
    return f"strengthen {skill} in the optimal-challenge zone (mastery {mastery:.0%})"


def plan_next_actions(
    user_id: str,
    language: str,
    *,
    constraints: PlanConstraints | None = None,
) -> list[LearningAction]:
    """Return a ranked, budget-fitting plan of next best learning actions.

    Candidates are drawn from due reviews (FSRS), grammar weaknesses, and
    ready-but-weak skills, scored by Expected Learning Value, ranked, and packed
    into the time budget. Always includes at least a conversation fallback so a
    brand-new learner still gets a sensible next step.
    """
    constraints = constraints or PlanConstraints()
    model = get_knowledge_model()
    beliefs = model.current_beliefs(user_id, language)
    mastery_by_skill = {s: b.mastery for s, b in beliefs.items()}

    candidates: list[LearningAction] = []
    candidates += _review_actions(user_id, language, constraints)
    candidates += _grammar_actions(user_id, language, constraints, mastery_by_skill)
    candidates += _skill_practice_actions(constraints, beliefs, mastery_by_skill)

    # Fallback: a conversation is always a valid next action.
    candidates.append(
        LearningAction(
            type=ActionType.CONTINUE_CONVERSATION,
            target="conversation",
            skill="speaking",
            reason="a natural conversation exercises many skills at once",
            priority=expected_learning_value(
                mastery=mastery_by_skill.get("speaking", 0.3),
                uncertainty=beliefs["speaking"].uncertainty if "speaking" in beliefs else 1.0,
                urgency=0.3,
                skill="speaking",
                estimated_minutes=estimated_minutes(ActionType.CONTINUE_CONVERSATION),
                constraints=constraints,
            ),
        )
    )

    # Rank by priority (desc), then pack into the time budget.
    candidates.sort(key=lambda a: a.priority, reverse=True)

    plan: list[LearningAction] = []
    remaining = constraints.time_available_minutes
    for action in candidates:
        if len(plan) >= constraints.max_actions:
            break
        if action.estimated_minutes <= remaining or not plan:
            plan.append(action)
            remaining -= action.estimated_minutes
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
