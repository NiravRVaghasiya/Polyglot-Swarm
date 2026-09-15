"""Mastery engine — prior belief + new evidence -> posterior belief.

For each skill, the engine takes the current belief (mastery, uncertainty, and
the effective evidence count that produced it) and a batch of evidence events,
and returns an updated belief. The update is a transparent, monotone
weighted-evidence rule:

- each event maps to a *signal* in [0, 1] (1 = demonstrates mastery, 0 =
  demonstrates a gap), derived from its ``assessment``;
- the signal is weighted by the event's ``confidence``;
- the belief moves toward the signal by an amount that shrinks as more evidence
  accumulates (early evidence matters more), and uncertainty shrinks with the
  effective observation count.

This is deliberately NOT a full Bayesian/IRT/DKT model — the plan says a robust
weighted-evidence model is enough for MVP and that the *interface* is what
matters. The engine is pure (no I/O), so it is trivially testable and the
scoring can be swapped later without touching callers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.learner import uncertainty

# Map an evidence ``assessment`` to a mastery signal in [0, 1].
# Positive assessments demonstrate competence; "incorrect" demonstrates a gap.
# Acceptable-variation classifications (regional/informal/...) are NOT negative
# evidence about the learner — they're weak-positive at most, so they carry a
# near-neutral signal and low weight.
_ASSESSMENT_SIGNAL: dict[str, float] = {
    "correct": 1.0,
    "observed": 0.75,  # produced/encountered a word — moderate positive
    "incorrect": 0.0,  # a genuine error — negative evidence
    "awkward": 0.35,  # non-idiomatic but understood
    "abstain": 0.5,  # the tutor wasn't sure — neutral
}

# Assessments that reflect acceptable variation rather than a learner gap.
_NEUTRAL_ASSESSMENTS = frozenset({"regional", "informal", "formal", "unusual", "acceptable"})


@dataclass
class SkillBelief:
    """The model's current belief about one skill."""

    skill: str
    mastery: float = 0.0
    uncertainty: float = 1.0
    sample_size: float = 0.0  # effective (confidence-weighted) observation count

    def clamp(self) -> SkillBelief:
        self.mastery = max(0.0, min(1.0, self.mastery))
        self.uncertainty = max(0.0, min(1.0, self.uncertainty))
        self.sample_size = max(0.0, self.sample_size)
        return self


def _signal(assessment: str | None) -> float | None:
    """Map an assessment to a signal in [0, 1], or ``None`` to ignore the event."""
    if assessment is None:
        return None
    key = assessment.lower()
    if key in _NEUTRAL_ASSESSMENTS:
        return 0.6  # mild positive: the learner produced valid (if marked) language
    return _ASSESSMENT_SIGNAL.get(key)


class MasteryEngine:
    """Updates skill beliefs from evidence via weighted-evidence blending."""

    def update_skill(self, prior: SkillBelief, events: list[dict[str, Any]]) -> SkillBelief:
        """Return the posterior belief for one skill given its events.

        ``events`` are evidence rows (dicts) with ``assessment`` and
        ``confidence``. Events with an unmappable assessment are ignored.
        """
        mastery = prior.mastery
        n = prior.sample_size
        for event in events:
            signal = _signal(event.get("assessment"))
            if signal is None:
                continue
            conf = float(event.get("confidence", 1.0))
            weight = uncertainty.blend_weight(n, conf)
            mastery = mastery + weight * (signal - mastery)
            n += conf
        belief = SkillBelief(
            skill=prior.skill,
            mastery=mastery,
            uncertainty=uncertainty.uncertainty_from_evidence(n),
            sample_size=n,
        )
        return belief.clamp()

    def update_from_events(
        self,
        priors: dict[str, SkillBelief],
        events: list[dict[str, Any]],
    ) -> dict[str, SkillBelief]:
        """Update every skill touched by ``events``, returning posteriors by skill.

        Events are grouped by their ``skill`` field; events with no skill (e.g.
        TURN_COMPLETED) are ignored. Skills with a prior but no new events are
        left unchanged and not returned (only touched skills are returned).
        """
        by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            skill = event.get("skill")
            if skill:
                by_skill[skill].append(event)

        posteriors: dict[str, SkillBelief] = {}
        for skill, skill_events in by_skill.items():
            prior = priors.get(skill, SkillBelief(skill=skill))
            posteriors[skill] = self.update_skill(prior, skill_events)
        return posteriors
