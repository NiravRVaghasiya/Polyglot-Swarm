"""Difficulty appropriateness for the planner.

Phase 7 needs a notion of "is this the right challenge level right now" without
duplicating the CEFR-stepping in :mod:`src.agents.adaptive` (which owns moving
the learner's level up/down from the evaluator's signal). This module answers a
different, complementary question the planner asks: given a mastery estimate and
its uncertainty, how much *learning value* is there in practising it now?

The classic "desirable difficulty" idea: items that are neither too easy
(already mastered) nor too hard (no foundation) carry the most learning value.
Uncertainty adds value too — practising something we're unsure about resolves
the model's ambiguity.
"""

from __future__ import annotations

# The mastery level of maximum learning value: the "optimal challenge" zone.
_OPTIMAL_MASTERY = 0.6


def desirable_difficulty(mastery: float) -> float:
    """Learning value from difficulty alone, peaking at the optimal-challenge zone.

    Returns a value in (0, 1]: ~1.0 near ``_OPTIMAL_MASTERY``, tapering toward 0
    for already-mastered (mastery→1) or not-yet-founded (mastery→0) items.
    """
    mastery = max(0.0, min(1.0, mastery))
    # A tent function peaking at _OPTIMAL_MASTERY.
    if mastery <= _OPTIMAL_MASTERY:
        return 0.2 + 0.8 * (mastery / _OPTIMAL_MASTERY)
    return 0.2 + 0.8 * ((1.0 - mastery) / (1.0 - _OPTIMAL_MASTERY))


def uncertainty_bonus(uncertainty: float) -> float:
    """Extra value for practising something the model is unsure about.

    Returns a multiplier in [1.0, 1.5]: resolving a high-uncertainty belief is
    worth more because it improves the model, not just the learner.
    """
    return 1.0 + 0.5 * max(0.0, min(1.0, uncertainty))


def difficulty_appropriate(mastery: float, *, fatigue: float = 0.0) -> bool:
    """Whether an item's difficulty is appropriate given current fatigue.

    When fatigued, avoid the hardest (lowest-mastery) items; otherwise anything
    below full mastery is fair game.
    """
    if fatigue > 0.6 and mastery < 0.3:
        return False
    return mastery < 0.95
