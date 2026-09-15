"""Normalization — canonicalize evidence fields before they are stored.

Raw observations come in with inconsistent casing/whitespace and, for grammar,
free-form rule names. Normalizing here means the belief layer aggregates
correctly: "Ser_vs_Estar", "ser vs estar", and "ser_vs_estar " all collapse to
one construction id, and lemmas/words are compared case-insensitively.
"""

from __future__ import annotations

import re

from src.evidence.events import EventType, LearningEvent

_WS_RE = re.compile(r"\s+")


def normalize_rule(rule: str) -> str:
    """Canonicalize a grammar rule/construction name to a stable id.

    Lowercase, trim, collapse internal whitespace to single underscores, and
    strip surrounding punctuation. Empty/garbage input becomes ``"unknown"``.
    """
    if not rule:
        return "unknown"
    text = _WS_RE.sub("_", rule.strip().lower())
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    return text or "unknown"


def normalize_word(word: str) -> str:
    """Canonicalize a word/lemma: trim and lowercase (word forms compare loosely)."""
    return _WS_RE.sub(" ", word.strip()).lower()


def normalize_event(event: LearningEvent) -> LearningEvent:
    """Return a normalized copy of ``event``.

    Only the fields used as aggregation keys are touched (``item_id`` for
    grammar/vocab); free-text ``observed``/``expected`` are trimmed but their
    case is preserved for display/evidence fidelity.
    """
    item_id = event.item_id
    if item_id is not None:
        if event.event_type in (EventType.GRAMMAR_ERROR, EventType.GRAMMAR_SUCCESS):
            item_id = normalize_rule(item_id)
        elif event.event_type in (
            EventType.VOCAB_OBSERVED,
            EventType.VOCAB_PRODUCED,
            EventType.REVIEW_RESULT,
        ):
            item_id = normalize_word(item_id)

    observed = event.observed.strip() if event.observed else event.observed
    expected = event.expected.strip() if event.expected else event.expected

    return event.model_copy(update={"item_id": item_id, "observed": observed, "expected": expected})


def normalize_all(events: list[LearningEvent]) -> list[LearningEvent]:
    """Normalize a batch of events."""
    return [normalize_event(e) for e in events]
