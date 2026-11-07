"""Evidence event types and the ``LearningEvent`` model.

An event is an immutable record of one observed thing. It carries: what kind of
event it is, which learner/language/session it belongs to, the competence it
concerns (skill -> subskill -> learning objective -> item), the task that
produced it (task type and difficulty, with unknown difficulty kept distinct
from a measured one), the observed vs expected values, an assessment, the
evaluator's reliability (``confidence``), and its provenance (source, model,
prompt and rubric versions). The learner model consumes these; it never
mutates them. Corrections are new events that *supersede* old ones
(ADR-0031).
"""

from __future__ import annotations

import hashlib
import json
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
    #: A generic graded observation about a skill: a task result with no more
    #: specific type. Bare evidence dicts without an ``event_type`` map here.
    SKILL_EVIDENCE = "SKILL_EVIDENCE"


class DifficultyBasis(StrEnum):
    """Where an event's task ``difficulty`` came from.

    ``UNKNOWN`` is deliberately distinct from any measured value: an unknown
    difficulty is never silently treated as "medium" evidence. The learner
    model discounts how informative such an observation is.
    """

    UNKNOWN = "unknown"
    #: Rated from a CEFR label (e.g. a language-pack construction's level).
    CEFR_LABEL = "cefr_label"
    #: The FSRS scheduler's per-card difficulty before the review.
    FSRS_CARD = "fsrs_card"
    #: Estimated from calibrated item statistics (no producer emits this yet).
    MEASURED = "measured"


#: Bumped when the event schema gains fields. Rows stored before the
#: provenance/difficulty overhaul (ADR-0031) read back as version 1.
EVENT_SCHEMA_VERSION = 3


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
    EventType.SKILL_EVIDENCE: None,
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

    # What competence the observation is about, from coarse to fine:
    # skill (grammar) -> subskill (a construction, a vocabulary dimension) ->
    # learning objective (a stable curriculum id) -> item (the lemma/rule).
    skill: str | None = None
    subskill: str | None = None
    objective_id: str | None = None
    item_id: str | None = None  # construction name, lemma, objective id, ...

    observed: str | None = None
    expected: str | None = None
    assessment: str | None = None  # correct | incorrect | awkward | abstain | ...
    #: How much the *evaluator's judgment* is trusted (a heuristic reliability,
    #: not a calibrated probability that the learner has mastered anything).
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # The task that produced the observation. ``difficulty`` is in [0, 1]
    # (0 = easiest A1-level task, 1 = hardest C2-level task) and is ``None``
    # when unknown; ``difficulty_basis`` says how it was obtained.
    task_type: str | None = None
    difficulty: float | None = Field(default=None, ge=0.0, le=1.0)
    difficulty_basis: DifficultyBasis = DifficultyBasis.UNKNOWN

    # Provenance (flattened for easy persistence).
    source: str = "unknown"
    session_id: str | None = None
    interaction_id: str | None = None
    model_version: str | None = None
    rubric_version: str | None = None
    prompt_version: str | None = None

    #: Evaluations sharing a correlation id judged the *same* learner
    #: production, so the learner model counts them as one observation.
    correlation_id: str | None = None
    #: The ``event_id`` this event corrects, if it is a correction.
    supersedes: str | None = None
    schema_version: int = EVENT_SCHEMA_VERSION

    payload: dict[str, Any] = Field(default_factory=dict)

    # Multimodal provenance (ADR-0034). ``modality`` is the channel the
    # learner's performance came through ("text" | "audio" | ...).
    # ``media_ref`` points at the captured asset and, when known, the
    # segment (``{"asset_id", "start", "end"}``). ``processing`` records the
    # machine stages that produced the observation (provider, model, latency).
    # ``transcription_confidence`` is the *recogniser's* confidence for
    # transcript-derived evidence; it is kept apart from ``confidence`` (the
    # evaluator's confidence about the learner) and the learner model
    # discounts by both.
    modality: str = "text"
    media_ref: dict[str, Any] | None = None
    processing: dict[str, Any] | None = None
    transcription_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    #: When the observation happened (ISO-8601, UTC).
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
        subskill: str | None = None,
        objective_id: str | None = None,
        task_type: str | None = None,
        difficulty: float | None = None,
        difficulty_basis: DifficultyBasis | None = None,
        correlation_id: str | None = None,
        supersedes: str | None = None,
        created_at: str | None = None,
        modality: str = "text",
        media_ref: dict[str, Any] | None = None,
        processing: dict[str, Any] | None = None,
        transcription_confidence: float | None = None,
    ) -> LearningEvent:
        """Build an event, defaulting ``skill`` from the event type if omitted.

        When the provenance does not carry an ``interaction_id``, fall back to
        the interaction currently in scope (Phase 17 observability), so evidence
        produced while handling a turn is correlated with that turn's model runs
        without every caller having to thread the id explicitly.

        A ``difficulty`` given without a ``difficulty_basis`` is recorded as
        ``MEASURED``; no difficulty means ``UNKNOWN``.
        """
        interaction_id = provenance.interaction_id
        if interaction_id is None:
            from src.observability.context import current_interaction

            interaction_id = current_interaction()
        if difficulty is None:
            basis = DifficultyBasis.UNKNOWN
        else:
            basis = difficulty_basis or DifficultyBasis.MEASURED
        extra: dict[str, Any] = {}
        if created_at is not None:
            extra["created_at"] = created_at
        return cls(
            event_type=event_type,
            user_id=user_id,
            language=language,
            skill=skill if skill is not None else EVENT_SKILL.get(event_type),
            subskill=subskill,
            objective_id=objective_id,
            item_id=item_id,
            observed=observed,
            expected=expected,
            assessment=assessment,
            confidence=confidence,
            task_type=task_type,
            difficulty=difficulty,
            difficulty_basis=basis,
            source=provenance.source,
            session_id=provenance.session_id,
            interaction_id=interaction_id,
            model_version=provenance.model_version,
            rubric_version=provenance.rubric_version,
            prompt_version=provenance.prompt_version,
            correlation_id=correlation_id,
            supersedes=supersedes,
            payload=payload or {},
            modality=modality,
            media_ref=media_ref,
            processing=processing,
            transcription_confidence=transcription_confidence,
            **extra,
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

    def fingerprint(self) -> str:
        """A content hash identifying "the same observation" across batches.

        Covers what was observed and how it was judged, not when or under which
        ``event_id``: two events with equal fingerprints are duplicate
        evaluations, and the learner model counts them once.
        """
        return evidence_fingerprint(self.model_dump(mode="json"))


#: The fields that make two evidence records "the same observation".
_FINGERPRINT_FIELDS = (
    "user_id",
    "language",
    "event_type",
    "skill",
    "subskill",
    "objective_id",
    "item_id",
    "observed",
    "expected",
    "assessment",
    "task_type",
    "session_id",
    "interaction_id",
    "source",
)


def evidence_fingerprint(record: dict[str, Any]) -> str:
    """Return the stable content fingerprint of an evidence record (dict form).

    Works on stored rows and bare dicts alike, so legacy rows without a stored
    fingerprint can be fingerprinted on read. Enum values are compared by
    their string value.
    """
    canonical = {key: _plain(record.get(key)) for key in _FINGERPRINT_FIELDS}
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, StrEnum) else value
