"""Planning constraints — the budget the plan must fit within.

The planner maximizes expected learning value *subject to* these constraints:
how much time the learner has, how tired they are, their goal (which skills to
weight), and how much difficulty to allow. Keeping constraints in one small
object makes the planner signature clean and the policy explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Goal -> the skills that goal weights more heavily. A learner aiming for
# "conversational" fluency should get more speaking/listening; a "reading"
# goal should get more reading/vocabulary. Unknown goals weight nothing extra.
GOAL_SKILL_WEIGHTS: dict[str, dict[str, float]] = {
    "conversational": {"speaking": 1.5, "listening": 1.3, "pragmatics": 1.2},
    "travel": {"speaking": 1.4, "listening": 1.3, "vocabulary": 1.2},
    "reading": {"reading": 1.5, "vocabulary": 1.3, "grammar": 1.1},
    "writing": {"writing": 1.5, "grammar": 1.3, "spelling": 1.2},
    "exam": {"grammar": 1.3, "reading": 1.2, "writing": 1.2, "listening": 1.1},
}


@dataclass
class PlanConstraints:
    """Constraints on a learning plan."""

    #: Minutes of learner time available for this plan.
    time_available_minutes: float = 15.0
    #: Fatigue in [0, 1]; higher fatigue favors shorter, lower-difficulty actions.
    fatigue: float = 0.0
    #: The learner's goal (keys of :data:`GOAL_SKILL_WEIGHTS`), or free text.
    goal: str = "conversational"
    #: Max number of actions to return.
    max_actions: int = 5
    #: Skills to explicitly avoid this session (e.g. just practised heavily).
    avoid_skills: frozenset[str] = field(default_factory=frozenset)

    def skill_weight(self, skill: str | None) -> float:
        """Return the goal-derived weight multiplier for a skill (default 1.0)."""
        if skill is None:
            return 1.0
        return GOAL_SKILL_WEIGHTS.get(self.goal, {}).get(skill, 1.0)

    def fatigue_penalty(self, estimated_minutes: float) -> float:
        """A multiplier in (0, 1] that penalizes long actions when fatigued.

        With zero fatigue there is no penalty. As fatigue rises, longer actions
        are discounted more, nudging the plan toward short retrieval practice.
        """
        if self.fatigue <= 0:
            return 1.0
        # Longer actions lose more value as fatigue grows.
        return max(0.2, 1.0 - self.fatigue * (estimated_minutes / 10.0))
