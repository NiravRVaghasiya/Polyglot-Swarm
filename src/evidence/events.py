"""Evidence event types and the ``LearningEvent`` model.

An event is an immutable record of one observed thing. It carries: what kind of
event it is, which learner/language/session it belongs to, the skill and item
it concerns, the observed vs expected values, an assessment, a confidence, and
its provenance. The learner model consumes these; it never mutates them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.evidence.provenance import Provenance


class EventType(StrEnum):
    """The kinds of learning evidence the pipeline understands."""

    TURN_COMPLETED = "TURN_COMPLETED"
    VOCAB_OBSERVED = "VOCAB_OBSERVED"
    VOCAB_PRODUCED = "VOCAB_PRODUCED"
    GRAMMAR_ERROR = "GRAMMAR_ERROR"
    GRAMMAR_SUCCESS = "GRAMMAR_SUCCESS"
    PRAGMATIC_EVENT = "PRAGMATIC_EVENT"
    PRONUNCIATION_EVENT = "PRONUNCIATION_EVENT"
    COMPREHENSION_RESULT = "COMPREHENSION_RESULT"
    REVIEW_RESULT = "REVIEW_RESULT"
    SCENARIO_OBJECTIVE_COMPLETED = "SCENARIO_OBJECTIVE_COMPLETED"


# Which skill each event type primarily informs (used to route evidence to the
# right skill dimension in the learner model). ``None`` = no single skill.
EVENT_SKILL: dict[EventType, str | None] = {
    EventType.TURN_COMPLETED: None,
    EventType.VOCAB_OBSERVED: "vocabulary",
    EventType.VOCAB_PRODUCED: "vocabulary",
    EventType.GRAMMAR_ERROR: "grammar",
    EventType.GRAMMAR_SUCCESS: "grammar",
    EventType.PRAGMATIC_EVENT: "pragmatics",
    EventType.PRONUNCIATION_EVENT: "pronunciation",
    EventType.COMPREHENSION_RESULT: "listening",
    EventType.REVIEW_RESULT: "vocabulary",
    EventType.SCENARIO_OBJECTIVE_COMPLETED: None,
}


class LearningEvent(BaseModel):
    """A single, immutable observation about a learner.

    Distinguishing this from the *belief* layer (vocabulary rows, error
    patterns, skill states) is the whole point: events are the ground truth of
    what was observed; beliefs are derived from many events.
    """

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: EventType
    user_id: str
    language: str

    skill: str | None = None
    item_id: str | None = None  # construction name, lemma, objective id, ...
    observed: str | None = None
    expected: str | None = None
    assessment: str | None = None  # correct | incorrect | awkward | abstain | ...
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Provenance (flattened for easy persistence).
    source: str = "unknown"
    session_id: str | None = None
    interaction_id: str | None = None
    model_version: str | None = None

    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(
        cls,
        event_type: EventType,
        user_id: str,
        language: str,
        *,
        provenance: Provenance,
        skill: str | None = None,
        item_id: str | None = None,
        observed: str | None = None,
        expected: str | None = None,
        assessment: str | None = None,
        confidence: float = 1.0,
        payload: dict[str, Any] | None = None,
    ) -> LearningEvent:
        """Build an event, defaulting ``skill`` from the event type if omitted.

        When the provenance does not carry an ``interaction_id``, fall back to
        the interaction currently in scope (Phase 17 observability), so evidence
        produced while handling a turn is correlated with that turn's model runs
        without every caller having to thread the id explicitly.
        """
        interaction_id = provenance.interaction_id
        if interaction_id is None:
            from src.observability.context import current_interaction

            interaction_id = current_interaction()
        return cls(
            event_type=event_type,
            user_id=user_id,
            language=language,
            skill=skill if skill is not None else EVENT_SKILL.get(event_type),
            item_id=item_id,
            observed=observed,
            expected=expected,
            assessment=assessment,
            confidence=confidence,
            source=provenance.source,
            session_id=provenance.session_id,
            interaction_id=interaction_id,
            model_version=provenance.model_version,
            payload=payload or {},
        )

    def dedup_key(self) -> tuple[str, str, str, str | None, str | None]:
        """A key identifying "the same observation" for deduplication.

        Two events with the same (session, type, skill, item, observed) are
        treated as duplicates within a batch — e.g. the same word extracted
        twice in one turn.
        """
        return (
            self.session_id or "",
            self.event_type.value,
            self.skill or "",
            self.item_id,
            self.observed,
        )
