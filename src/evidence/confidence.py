"""Confidence scoring for evidence events.

Not every observation is equally trustworthy. A grammar error flagged as
"critical" by the analyzer is stronger evidence than a "minor" one; a word the
learner *produced* is stronger evidence of knowledge than one merely *observed*
in the tutor's reply. This module assigns a default confidence when a producer
didn't supply one, so the learner model can weight evidence rather than treat
every event as certain.

These are deliberately simple, transparent heuristics. Proper calibration
(comparing predicted confidence to observed correctness) is a later phase; the
interface is what matters now.
"""

from __future__ import annotations

from src.evidence.events import EventType

# Base confidence by event type — how much we trust the observation itself.
_BASE_BY_TYPE: dict[EventType, float] = {
    EventType.TURN_COMPLETED: 1.0,
    EventType.VOCAB_OBSERVED: 0.5,  # seen in tutor output != learner knows it
    EventType.VOCAB_PRODUCED: 0.8,  # learner used it -> stronger signal
    EventType.GRAMMAR_ERROR: 0.7,
    EventType.GRAMMAR_SUCCESS: 0.6,
    EventType.PRAGMATIC_EVENT: 0.6,
    EventType.PRONUNCIATION_EVENT: 0.6,
    EventType.COMPREHENSION_RESULT: 0.8,
    EventType.REVIEW_RESULT: 0.95,  # explicit graded review -> very strong
    EventType.SCENARIO_OBJECTIVE_COMPLETED: 0.9,
}

# Multiplier by grammar severity (only applies to grammar events).
_SEVERITY_WEIGHT: dict[str, float] = {
    "minor": 0.6,
    "moderate": 0.85,
    "critical": 1.0,
}


def base_confidence(event_type: EventType) -> float:
    """Return the base confidence for an event type."""
    return _BASE_BY_TYPE.get(event_type, 0.7)


def severity_weight(severity: str | None) -> float:
    """Return the confidence multiplier for a grammar severity label."""
    if severity is None:
        return 1.0
    return _SEVERITY_WEIGHT.get(severity.lower(), 1.0)


def score(
    event_type: EventType,
    *,
    provided: float | None = None,
    severity: str | None = None,
) -> float:
    """Compute a confidence in [0, 1] for an event.

    If a producer already supplied a confidence, it is respected (clamped).
    Otherwise the base-by-type value is used, scaled by grammar severity when
    relevant.
    """
    if provided is not None:
        return max(0.0, min(1.0, provided))
    value = base_confidence(event_type) * severity_weight(severity)
    return max(0.0, min(1.0, value))
