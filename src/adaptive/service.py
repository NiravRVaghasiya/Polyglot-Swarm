"""Store-backed entry point to the next-best-activity engine.

:mod:`src.adaptive.planner` is pure: it plans over a
:class:`~src.adaptive.snapshot.LearnerSnapshot`. This module is the one place
that builds a snapshot from the stores, runs the planner and records the
served plan in the audit trail. ``/learner/plan``, ``/learner/insights``,
``/learner/recommendations`` and ``polyglot plan`` all go through
:func:`recommend`, so every surface shows the same engine's decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.adaptive.constraints import PlanConstraints
from src.adaptive.planner import Plan
from src.adaptive.planner import plan as plan_activities


@dataclass(frozen=True)
class ServedPlan:
    plan: Plan
    #: Audit row id of the recorded decision, or ``None`` when not recorded.
    decision_id: int | None


def recommend(
    user_id: str,
    language: str,
    *,
    minutes: float = 15.0,
    goal: str = "conversational",
    max_actions: int = 5,
    record: bool = True,
) -> ServedPlan:
    """Plan the learner's next activities from their stored evidence.

    With ``record`` the plan is appended to the audit trail as a
    ``recommendation`` decision. The next snapshot reads the last recorded
    recommendation to keep task difficulty continuous, so pass
    ``record=False`` only for previews that the learner does not act on.
    """
    from src.adaptive import audit
    from src.adaptive.snapshot import snapshot_from_store

    snapshot = snapshot_from_store(user_id, language, goal=goal)
    constraints = PlanConstraints(
        time_available_minutes=minutes, goal=goal, max_actions=max_actions
    )
    result = plan_activities(snapshot, constraints=constraints)
    decision_id = None
    if record:
        decision_id = audit.record_decision(
            user_id,
            language,
            kind="recommendation",
            engine=result.engine,
            input_digest=result.input_digest,
            payload=result.as_dict(),
        )
    return ServedPlan(result, decision_id)
