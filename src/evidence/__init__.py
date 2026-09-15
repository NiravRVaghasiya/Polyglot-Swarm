"""Evidence pipeline — the record of *what happened* in a learning interaction.

This package implements Phase 3 of the plan. Its purpose is to separate two
things the rest of the system keeps conflating:

    what happened            (evidence events — immutable, append-only)
    what we believe          (the learner model / error patterns / vocabulary)

Every interaction emits structured :class:`~src.evidence.events.LearningEvent`
records (a grammar error observed, a word produced, a turn completed, a review
result). Those events are normalized, deduplicated, given a confidence and a
provenance stamp, and persisted. The belief layer (vocabulary store, grammar
error taxonomy, and later the learner knowledge model) is then derived *from*
the events — never updated directly on an LLM's say-so.

That gives explainability, reproducibility, rollback, and longitudinal
analysis, which is exactly what the plan calls the "most important new
subsystem".

Public surface:
- :mod:`events`      — event types + the ``LearningEvent`` model.
- :mod:`provenance`  — where an event came from (model/component + ids).
- :mod:`confidence`  — confidence scoring / calibration helpers.
- :mod:`normalizer`  — canonicalize raw fields.
- :mod:`deduplicator`— collapse duplicate events within a batch.
- :mod:`extractor`   — turn a LearnerState / turn into events.
- :mod:`store`       — persist and query events (``evidence`` table).
- :mod:`pipeline`    — the end-to-end ``process`` orchestration.
"""

from src.evidence.events import EventType, LearningEvent
from src.evidence.pipeline import build_events, process_session
from src.evidence.provenance import Provenance

__all__ = [
    "EventType",
    "LearningEvent",
    "Provenance",
    "build_events",
    "process_session",
]
