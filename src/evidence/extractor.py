"""Extraction — turn the raw outputs of a session into evidence events.

The orchestrator accumulates per-turn agent outputs on the ``LearnerState``:
``grammar_errors``, ``new_vocabulary``, and conversation ``messages``. This
module maps those into structured :class:`LearningEvent` records with the right
type, item id, assessment, confidence, and provenance — the raw material the
belief layer is then derived from.

It deliberately does NOT touch storage or the learner model; it is a pure
transform (state -> events) so it is trivially testable and reusable by the
CLI, API, and future voice pipeline.
"""

from __future__ import annotations

from typing import Any

from src.evidence import confidence
from src.evidence.events import EventType, LearningEvent
from src.evidence.provenance import Provenance


def extract_grammar_events(
    user_id: str,
    language: str,
    grammar_errors: list[dict[str, Any]],
    *,
    provenance: Provenance,
) -> list[LearningEvent]:
    """One GRAMMAR_ERROR event per detected error.

    The event's ``assessment`` reflects the Phase 4 taxonomy classification
    (``wrong``/``awkward``/...) rather than a hardcoded ``incorrect``, and its
    confidence comes from the agent's calibrated value when present. The
    construction id (preferred) or rule becomes the ``item_id``.
    """
    events: list[LearningEvent] = []
    for err in grammar_errors:
        construction = err.get("construction") or err.get("rule") or "unknown"
        severity = err.get("severity")
        classification = (err.get("classification") or "wrong").lower()
        conf = confidence.score(
            EventType.GRAMMAR_ERROR,
            provided=err.get("confidence"),
            severity=severity,
        )
        events.append(
            LearningEvent.create(
                EventType.GRAMMAR_ERROR,
                user_id,
                language,
                provenance=provenance,
                item_id=construction,
                observed=err.get("original"),
                expected=err.get("correction"),
                # "wrong" -> "incorrect" so the belief layer / analytics keep
                # their existing semantics; other classifications flow through.
                assessment="incorrect" if classification == "wrong" else classification,
                confidence=conf,
                payload={
                    "explanation": err.get("explanation", ""),
                    "severity": severity or "moderate",
                    "classification": classification,
                    "alternatives": err.get("alternatives", []),
                },
            )
        )
    return events


def extract_vocabulary_events(
    user_id: str,
    language: str,
    new_vocabulary: list[dict[str, Any]],
    *,
    provenance: Provenance,
) -> list[LearningEvent]:
    """One VOCAB_PRODUCED event per new word encountered in the turn."""
    events: list[LearningEvent] = []
    for item in new_vocabulary:
        word = item.get("word")
        if not word:
            continue
        events.append(
            LearningEvent.create(
                EventType.VOCAB_PRODUCED,
                user_id,
                language,
                provenance=provenance,
                item_id=word,
                observed=word,
                assessment="observed",
                confidence=confidence.score(EventType.VOCAB_PRODUCED),
                payload={
                    "translation": item.get("translation", ""),
                    "pos": item.get("pos", ""),
                    "context_sentence": item.get("context_sentence", ""),
                },
            )
        )
    return events


def extract_turn_events(
    user_id: str,
    language: str,
    messages: list[dict[str, Any]],
    *,
    provenance: Provenance,
) -> list[LearningEvent]:
    """One TURN_COMPLETED event per user turn (the learner's own production)."""
    events: list[LearningEvent] = []
    for msg in messages:
        if msg.get("role") != "user" or not msg.get("content"):
            continue
        events.append(
            LearningEvent.create(
                EventType.TURN_COMPLETED,
                user_id,
                language,
                provenance=provenance,
                observed=msg["content"],
                confidence=confidence.score(EventType.TURN_COMPLETED),
            )
        )
    return events


def extract_from_state(state: dict[str, Any]) -> list[LearningEvent]:
    """Extract all events from a completed session's ``LearnerState``.

    Reads ``grammar_errors``, ``new_vocabulary``, and ``messages`` from the
    state dict. Provenance is stamped from the session id.
    """
    user_id = state["user_id"]
    language = state["language"]
    session_id = state.get("session_id")
    provenance = Provenance(source="session-extractor-v1", session_id=session_id)

    events: list[LearningEvent] = []
    events += extract_turn_events(
        user_id, language, state.get("messages", []), provenance=provenance
    )
    events += extract_grammar_events(
        user_id, language, state.get("grammar_errors", []), provenance=provenance
    )
    events += extract_vocabulary_events(
        user_id, language, state.get("new_vocabulary", []), provenance=provenance
    )
    return events
