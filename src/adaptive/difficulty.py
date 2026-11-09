"""Adaptive task difficulty (ADR-0033).

Chooses how demanding the next task on an objective should be, from the
learner's demonstrated ability on that objective.

**Two kinds of difficulty, kept apart.**

- **Linguistic complexity** is a property of the content. It is the CEFR
  level of the construction or word, and is fixed: scaffolding cannot turn a
  B2 construction into A1 content.
- **Task difficulty** is how demanding the task is: more or less support,
  recognition versus production, simple versus complex frames. It sits on the
  same ``[0, 1]`` scale as evidence difficulty. It can move within a window
  of ``± TASK_WINDOW`` around the content's complexity.

**Rule.**

1. **Target zone.** Aim for a predicted success probability of
   :data:`TARGET_SUCCESS`, within :data:`SUCCESS_ZONE`: challenging, but
   rarely overwhelming.
2. **Uncertainty.** The ability used is a lower posterior quantile
   (``theta - k * se``). The less evidence there is, the easier the task,
   rather than guessing high.
3. **Patterns** (:class:`~src.adaptive.learner_model.Pattern`):
   - A *temporary dip* (one bad session) holds the previous difficulty, so an
     isolated bad session never lowers it.
   - A *persistent decline* or *persistent weakness* allows a decrease.
   - An *improving* pattern, or stable success, allows an increase.
4. **Bounded steps.** Difficulty rises by at most :data:`MAX_STEP_UP` and
   falls by at most :data:`MAX_STEP_DOWN` per decision, so progression is
   gradual.
5. **No evidence.** With insufficient evidence, the task sits at the
   content's own complexity, a neutral probe.

Every decision records its inputs and a reason. It is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.adaptive.learner_model import (
    Pattern,
    SubskillEstimate,
    difficulty_logit,
    logit_to_difficulty,
)
from src.evidence.difficulty import difficulty_to_cefr
from src.learner.estimation import EvidenceStatus
from src.util import logit as _logit

TARGET_SUCCESS = 0.75
SUCCESS_ZONE = (0.65, 0.85)
#: How far task difficulty may move from the content's complexity.
TASK_WINDOW = 0.15
MAX_STEP_UP = 0.08
MAX_STEP_DOWN = 0.12
#: Posterior-quantile factor: use ``theta - UNCERTAINTY_K * se``.
UNCERTAINTY_K = 0.5


@dataclass(frozen=True)
class DifficultyDecision:
    objective_id: str
    task_difficulty: float
    #: CEFR level of the content (linguistic complexity), unchanged by scaffolding.
    linguistic_level: str | None
    content_difficulty: float | None
    #: Task relative to content: "scaffolded" | "standard" | "stretch".
    task_tier: str
    predicted_success: float
    predicted_low: float
    predicted_high: float
    previous_difficulty: float | None
    step: float
    #: Which limit shaped the decision, if any.
    bounded_by: str | None
    pattern: str
    status: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "task_difficulty": round(self.task_difficulty, 4),
            "linguistic_level": self.linguistic_level,
            "content_difficulty": None
            if self.content_difficulty is None
            else round(self.content_difficulty, 4),
            "task_tier": self.task_tier,
            "predicted_success": round(self.predicted_success, 4),
            "predicted_interval": [round(self.predicted_low, 4), round(self.predicted_high, 4)],
            "previous_difficulty": None
            if self.previous_difficulty is None
            else round(self.previous_difficulty, 4),
            "step": round(self.step, 4),
            "bounded_by": self.bounded_by,
            "pattern": self.pattern,
            "status": self.status,
            "reason": self.reason,
        }


def _tier(task: float, content: float | None) -> str:
    if content is None:
        return "standard"
    if task < content - 0.04:
        return "scaffolded"
    if task > content + 0.04:
        return "stretch"
    return "standard"


def choose_difficulty(
    estimate: SubskillEstimate,
    *,
    objective_id: str,
    content_difficulty: float | None,
    linguistic_level: str | None = None,
    previous_difficulty: float | None = None,
    target_success: float = TARGET_SUCCESS,
) -> DifficultyDecision:
    """Pick the next task difficulty for one objective (see module docstring)."""
    content = content_difficulty
    level = linguistic_level or (difficulty_to_cefr(content) if content is not None else None)
    lo_window = 0.0 if content is None else max(0.0, content - TASK_WINDOW)
    hi_window = 1.0 if content is None else min(1.0, content + TASK_WINDOW)
    status = estimate.status
    pattern = estimate.pattern
    bounded_by: str | None = None

    if status == EvidenceStatus.INSUFFICIENT.value:
        ideal = content if content is not None else 0.5
        reason = "not enough evidence on this objective: a neutral task at the content's level"
    else:
        cautious = estimate.ability - UNCERTAINTY_K * estimate.ability_se
        ideal = logit_to_difficulty(cautious - _logit(target_success))
        reason = (
            f"aims for ~{target_success:.0%} success from demonstrated ability "
            f"(lower posterior estimate, {estimate.independent_count} observations)"
        )

    chosen = ideal
    if previous_difficulty is not None:
        if pattern == Pattern.TEMPORARY_DIP and chosen < previous_difficulty:
            chosen = previous_difficulty
            bounded_by = "temporary_dip_hold"
            reason += "; one weak session is treated as a fluctuation: difficulty held"
        elif chosen > previous_difficulty + MAX_STEP_UP:
            chosen = previous_difficulty + MAX_STEP_UP
            bounded_by = "max_step_up"
            reason += f"; raised gradually (at most +{MAX_STEP_UP})"
        elif chosen < previous_difficulty - MAX_STEP_DOWN:
            chosen = previous_difficulty - MAX_STEP_DOWN
            bounded_by = "max_step_down"
            reason += f"; lowered gradually (at most -{MAX_STEP_DOWN})"
        if (
            chosen < previous_difficulty
            and bounded_by != "temporary_dip_hold"
            and pattern not in (Pattern.PERSISTENT_DECLINE, Pattern.PERSISTENT_WEAKNESS)
            and status != EvidenceStatus.INSUFFICIENT.value
            and estimate.p_success(previous_difficulty)[0] >= SUCCESS_ZONE[0]
        ):
            # Still inside the success zone at the old difficulty: no need to
            # step down without a persistent pattern.
            chosen = previous_difficulty
            bounded_by = "within_success_zone"
            reason += "; still within the success zone: difficulty kept"
    if chosen < lo_window:
        chosen, bounded_by = lo_window, "content_window_low"
        reason += "; at the most scaffolded task this content allows (check prerequisites)"
    elif chosen > hi_window:
        chosen, bounded_by = hi_window, "content_window_high"
        reason += "; at the most demanding task this content allows (ready to advance)"
    chosen = max(0.0, min(1.0, chosen))
    p, low, high = estimate.p_success(chosen)
    step = 0.0 if previous_difficulty is None else chosen - previous_difficulty
    return DifficultyDecision(
        objective_id=objective_id,
        task_difficulty=chosen,
        linguistic_level=level,
        content_difficulty=content,
        task_tier=_tier(chosen, content),
        predicted_success=p,
        predicted_low=low,
        predicted_high=high,
        previous_difficulty=previous_difficulty,
        step=step,
        bounded_by=bounded_by,
        pattern=pattern,
        status=status,
        reason=reason,
    )


def performance_curve(
    estimate: SubskillEstimate, difficulties: tuple[float, ...] | None = None
) -> list[dict[str, float | str]]:
    """Expected success across difficulties (CEFR band midpoints by default)."""
    points = difficulties or tuple((2 * i + 1) / 12.0 for i in range(6))
    out: list[dict[str, float | str]] = []
    for d in points:
        p, lo, hi = estimate.p_success(d)
        out.append(
            {
                "difficulty": round(d, 4),
                "cefr": difficulty_to_cefr(d),
                "p_success": round(p, 4),
                "low": round(lo, 4),
                "high": round(hi, 4),
            }
        )
    return out


__all__ = [
    "DifficultyDecision",
    "MAX_STEP_DOWN",
    "MAX_STEP_UP",
    "SUCCESS_ZONE",
    "TARGET_SUCCESS",
    "TASK_WINDOW",
    "choose_difficulty",
    "difficulty_logit",
    "performance_curve",
]
