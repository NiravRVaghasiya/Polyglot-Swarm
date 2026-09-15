"""Verification policies — thresholds and the confidence→decision mapping.

Centralizes the policy the verifier enforces so it is explicit and tunable:
- which corrections are *high-impact* (worth a careful verification pass);
- how a confidence maps to accept / revise / reject / abstain.

Keeping this here (not scattered in the evaluator) makes the safety posture a
single, auditable place — a false correction is the worst outcome, so the
defaults are conservative: below the abstain threshold we suppress rather than
risk teaching wrong language.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    """The verifier's possible outcomes for a candidate correction."""

    ACCEPT = "accept"  # keep the correction as-is
    REVISE = "revise"  # keep, but use the verifier's revised correction
    REJECT = "reject"  # drop it — it was a false positive
    ABSTAIN = "abstain"  # not confident either way — suppress rather than risk it


# Corrections at/above this confidence are accepted without further doubt.
ACCEPT_THRESHOLD = 0.75
# Below this, the verifier abstains (suppresses) rather than assert an error.
ABSTAIN_THRESHOLD = 0.5

# Severities considered high-impact (a wrong correction here is most damaging).
_HIGH_IMPACT_SEVERITIES = frozenset({"critical", "moderate"})


def is_high_impact(error: dict[str, Any]) -> bool:
    """Whether a candidate correction warrants a careful verification pass.

    High-impact = a genuine (``wrong``/``awkward``) correction at a non-trivial
    severity. Minor/typo-level or already-classified acceptable variation is
    low-impact and can be handled by the cheap path.
    """
    classification = (error.get("classification") or "wrong").lower()
    if classification not in ("wrong", "awkward"):
        return False
    severity = (error.get("severity") or "moderate").lower()
    return severity in _HIGH_IMPACT_SEVERITIES


def decide(confidence: float, *, has_revision: bool = False) -> Decision:
    """Map a confidence (and whether a revision was offered) to a decision.

    - >= ACCEPT_THRESHOLD  -> ACCEPT (or REVISE if a better form was offered)
    - >= ABSTAIN_THRESHOLD -> REVISE if offered, else ACCEPT (still fairly sure)
    - <  ABSTAIN_THRESHOLD -> ABSTAIN (suppress; do not assert an error)
    """
    confidence = max(0.0, min(1.0, confidence))
    if confidence < ABSTAIN_THRESHOLD:
        return Decision.ABSTAIN
    if has_revision:
        return Decision.REVISE
    return Decision.ACCEPT
