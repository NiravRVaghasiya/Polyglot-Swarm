"""The mastery -> CEFR band curve, shared by the learner model and assessment.

Lives in :mod:`src.learner` (not :mod:`src.assessment`) so the estimation
engine can label per-skill bands without importing the assessment package,
which itself depends on the learner model. ``src.assessment.cefr_profile``
re-exports :func:`mastery_to_cefr` for existing callers.

The curve is a fixed, conservative mapping (it needs high mastery for the top
bands). It is *not* empirically calibrated against expert ratings; see
``docs/learner-model.md``.
"""

from __future__ import annotations

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

# Mastery in [0, 1] -> CEFR band. Each band spans a mastery range.
MASTERY_BANDS: list[tuple[float, str]] = [
    (0.15, "A1"),
    (0.35, "A2"),
    (0.55, "B1"),
    (0.75, "B2"),
    (0.90, "C1"),
]


def mastery_to_cefr(mastery: float) -> str:
    """Map a mastery score in [0, 1] to a CEFR band (A1..C2)."""
    mastery = max(0.0, min(1.0, mastery))
    for bound, level in MASTERY_BANDS:
        if mastery < bound:
            return level
    return "C2"


def band_index(level: str) -> int:
    """Return the ordinal of a CEFR band (A1=0 .. C2=5)."""
    return CEFR_ORDER.index(level)
