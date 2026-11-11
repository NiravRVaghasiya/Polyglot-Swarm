"""Uncertainty helpers for the learner model.

The learner model reports not just a mastery estimate but how *confident* it is
in that estimate. Uncertainty starts high (we know nothing about a new learner)
and shrinks as evidence accumulates. These helpers keep that logic in one place
so the mastery engine, assessment, and UI agree on what uncertainty means.
"""

from __future__ import annotations

# With this many (confidence-weighted) observations, uncertainty is ~halved
# relative to the prior. A gentle curve: informative but not overconfident.
_HALF_LIFE = 5.0


def uncertainty_from_evidence(effective_n: float) -> float:
    """Map an effective observation count to an uncertainty in [0, 1].

    ``effective_n`` is the sum of evidence confidences (not a raw count), so
    weak observations reduce uncertainty less than strong ones. Uncertainty
    decays as ``0.5 ** (n / half_life)`` from a prior of 1.0 (no evidence) toward
    0.0 (lots of evidence).
    """
    if effective_n <= 0:
        return 1.0
    decayed = float(0.5 ** (effective_n / _HALF_LIFE))
    return max(0.0, min(1.0, decayed))


def blend_weight(prior_n: float, new_confidence: float) -> float:
    """How much a new observation should move the belief.

    Early observations move the belief a lot (little prior evidence); later ones
    move it less. Scaled by the observation's own confidence.
    """
    prior_n = max(0.0, prior_n)
    return max(0.0, min(1.0, new_confidence / (prior_n + 1.0)))
