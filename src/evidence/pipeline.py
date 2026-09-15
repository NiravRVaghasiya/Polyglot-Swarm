"""The evidence pipeline: state -> events -> normalized -> deduped -> stored.

This is the single entry point the orchestrator calls at the end of a session.
It runs the full transform and persists the result, returning the events so the
caller can derive the belief layer (vocabulary rows, grammar error taxonomy)
*from* the same events rather than from the raw LLM output.
"""

from __future__ import annotations

from typing import Any

from src.evidence import deduplicator, extractor, normalizer, store
from src.evidence.events import LearningEvent


def build_events(state: dict[str, Any]) -> list[LearningEvent]:
    """Run extract -> normalize -> dedup on a session state (no persistence).

    Pure function, useful for tests and for callers that want the events
    without writing them.
    """
    events = extractor.extract_from_state(state)
    events = normalizer.normalize_all(events)
    events = deduplicator.deduplicate(events)
    return events


def process_session(state: dict[str, Any], *, persist: bool = True) -> list[LearningEvent]:
    """Build and (optionally) persist the evidence for a completed session.

    Returns the final, normalized, deduplicated events.
    """
    events = build_events(state)
    if persist:
        store.record_events(events)
    return events
