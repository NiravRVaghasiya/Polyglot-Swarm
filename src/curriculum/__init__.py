"""Curriculum planner — the Next Best Learning Action engine.

This is the strategic heart of the product (Phase 7). Given the learner model
(what they can and cannot do), what is due for review, their goal, and the time
and energy available, the planner selects the highest-value next learning
action:

    argmax  Expected Learning Value
    subject to goal, time, fatigue, difficulty, due reviews, skill balance.

The planner is deterministic and pure over its inputs (it reads the belief
stores but calls no LLM), so it is fast, testable, and explainable — every
action it proposes carries a human-readable reason.

The division of labour with FSRS is deliberate (Phase 8):
- the curriculum planner decides **what** the learner should practise;
- FSRS decides **when** an item is due for review.
"""

from src.curriculum.actions import ActionType, LearningAction
from src.curriculum.constraints import PlanConstraints
from src.curriculum.planner import plan_next_actions, plan_next_best

__all__ = [
    "ActionType",
    "LearningAction",
    "PlanConstraints",
    "plan_next_actions",
    "plan_next_best",
]
