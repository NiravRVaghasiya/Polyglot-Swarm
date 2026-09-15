"""Learning actions — the vocabulary of things the planner can propose.

An action is one concrete learning interaction the tutor could deliver next.
The planner ranks candidate actions by expected learning value and returns the
best few. Each action is explainable (it carries a ``reason``) and estimable
(``priority`` and an ``estimated_minutes`` cost).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActionType(StrEnum):
    """The kinds of next-best learning actions (from the plan)."""

    CONTINUE_CONVERSATION = "continue_conversation"
    REVIEW_VOCAB = "review_vocab"
    TARGET_GRAMMAR = "target_grammar"
    CONTRAST_TWO_FORMS = "contrast_two_forms"
    PRONUNCIATION_DRILL = "pronunciation_drill"
    LISTENING_CHECK = "listening_check"
    WRITING_EXERCISE = "writing_exercise"
    READING = "reading"
    RETRIEVAL_PRACTICE = "retrieval_practice"
    SCENARIO = "scenario"
    TRANSFER_EXERCISE = "transfer_exercise"


# Rough time cost (minutes) per action type — used to fit a plan into the time
# budget. Deliberately coarse; refined later with real telemetry.
_ESTIMATED_MINUTES: dict[ActionType, float] = {
    ActionType.CONTINUE_CONVERSATION: 8.0,
    ActionType.REVIEW_VOCAB: 1.0,
    ActionType.TARGET_GRAMMAR: 5.0,
    ActionType.CONTRAST_TWO_FORMS: 4.0,
    ActionType.PRONUNCIATION_DRILL: 3.0,
    ActionType.LISTENING_CHECK: 4.0,
    ActionType.WRITING_EXERCISE: 6.0,
    ActionType.READING: 6.0,
    ActionType.RETRIEVAL_PRACTICE: 2.0,
    ActionType.SCENARIO: 10.0,
    ActionType.TRANSFER_EXERCISE: 4.0,
}


def estimated_minutes(action_type: ActionType) -> float:
    """Return the default time cost for an action type."""
    return _ESTIMATED_MINUTES.get(action_type, 5.0)


@dataclass
class LearningAction:
    """One proposed next learning action.

    Attributes:
        type: the kind of action.
        target: what it concerns — a skill, construction id, lemma, or scenario id.
        skill: the primary skill this action develops (for balance accounting).
        reason: a short, human-readable justification (explainable recommendations).
        priority: expected learning value in [0, 1]; higher = more valuable now.
        estimated_minutes: rough time cost.
        payload: extra structured detail (e.g. the due item, the two forms to contrast).
    """

    type: ActionType
    target: str
    skill: str | None = None
    reason: str = ""
    priority: float = 0.0
    estimated_minutes: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.priority = max(0.0, min(1.0, self.priority))
        if not self.estimated_minutes:
            self.estimated_minutes = estimated_minutes(self.type)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "target": self.target,
            "skill": self.skill,
            "reason": self.reason,
            "priority": round(self.priority, 3),
            "estimated_minutes": self.estimated_minutes,
            "payload": self.payload,
        }
