"""Expected Learning Value — the scoring function the planner maximizes.

Every candidate action is scored by its Expected Learning Value (ELV): how much
the learner (and the model's belief about the learner) is expected to gain from
doing it now. ELV combines:

- **desirable difficulty**: value peaks in the optimal-challenge zone
  (:mod:`src.curriculum.difficulty`);
- **model uncertainty**: resolving an uncertain belief is worth more;
- **urgency**: overdue reviews and frequent weaknesses are more pressing;
- **goal weight**: skills the learner's goal cares about count for more
  (:mod:`src.curriculum.constraints`);
- **fatigue**: long actions are discounted when the learner is tired.

Keeping ELV a small, transparent function (no LLM, no hidden state) makes plans
explainable and reproducible — a requirement of the product (explainable
recommendations).
"""

from __future__ import annotations

from src.curriculum import difficulty
from src.curriculum.constraints import PlanConstraints


def expected_learning_value(
    *,
    mastery: float,
    uncertainty: float,
    urgency: float,
    skill: str | None,
    estimated_minutes: float,
    constraints: PlanConstraints,
) -> float:
    """Return the expected learning value of an action in [0, 1].

    Args:
        mastery: current mastery of the target (0..1).
        uncertainty: model uncertainty about the target (0..1).
        urgency: how pressing this is (0..1) — e.g. overdue-ness, error frequency.
        skill: the primary skill the action develops (for goal weighting).
        estimated_minutes: the action's time cost.
        constraints: the plan's constraints (goal, fatigue, ...).
    """
    base = difficulty.desirable_difficulty(mastery)
    value = base * difficulty.uncertainty_bonus(uncertainty)
    # Blend in urgency: urgent items get a floor boost.
    value = 0.7 * value + 0.3 * max(0.0, min(1.0, urgency))
    # Goal weighting and fatigue.
    value *= constraints.skill_weight(skill)
    value *= constraints.fatigue_penalty(estimated_minutes)
    return max(0.0, min(1.0, value))


def review_urgency(overdue_rank: int, total_due: int) -> float:
    """Urgency for a review item by its position in the due queue (most overdue first)."""
    if total_due <= 0:
        return 0.0
    # The most overdue item (rank 0) is most urgent.
    return max(0.3, 1.0 - overdue_rank / max(total_due, 1))


def weakness_urgency(occurrences: int, max_occurrences: int) -> float:
    """Urgency for a grammar weakness by how often the learner makes it."""
    if max_occurrences <= 0:
        return 0.5
    return max(0.3, min(1.0, occurrences / max_occurrences))
