"""Task-difficulty helpers for evidence events (ADR-0031).

Difficulty is stored on an event as a number in ``[0, 1]`` (0 = the easiest
A1-level task, 1 = the hardest C2-level task) together with a
:class:`~src.evidence.events.DifficultyBasis` saying where it came from. An
unknown difficulty is ``None`` with basis ``UNKNOWN`` — it is never replaced by a
"medium" default.

Assumptions (documented in ``docs/learner-model.md``):

- A CEFR label maps to the midpoint of its sixth of the scale (A1 -> 1/12,
  A2 -> 3/12, ... C2 -> 11/12). It is a rating of the *content*, not a
  measurement of how hard learners find it.
- FSRS card difficulty ``D`` (1..10) maps linearly to ``(D - 1) / 9``. It is
  the scheduler's per-learner, per-card estimate before the review.
"""

from __future__ import annotations

CEFR_ORDER = ("A1", "A2", "B1", "B2", "C1", "C2")


def cefr_to_difficulty(level: str | None) -> float | None:
    """Map a CEFR label to a difficulty in ``[0, 1]``, or ``None`` if unrecognised."""
    if not level:
        return None
    key = level.strip().upper()[:2]
    if key not in CEFR_ORDER:
        return None
    return (2 * CEFR_ORDER.index(key) + 1) / 12.0


def difficulty_to_cefr(difficulty: float) -> str:
    """Inverse of :func:`cefr_to_difficulty`: the band a difficulty falls in."""
    d = max(0.0, min(1.0, difficulty))
    return CEFR_ORDER[min(5, int(d * 6))]


def fsrs_to_difficulty(card_difficulty: float | None) -> float | None:
    """Map an FSRS card difficulty (1..10) to ``[0, 1]``, or ``None`` if absent."""
    if card_difficulty is None:
        return None
    try:
        value = float(card_difficulty)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, (value - 1.0) / 9.0))
