"""Deduplication — collapse duplicate observations within a batch.

A single turn can legitimately surface the same observation more than once (the
same word extracted twice, the same construction flagged in two clauses).
Persisting each as separate evidence would double-count and skew the learner
model. This collapses events sharing a :meth:`LearningEvent.dedup_key`, keeping
the one with the highest confidence so the strongest signal survives.
"""

from __future__ import annotations

from src.evidence.events import LearningEvent


def deduplicate(events: list[LearningEvent]) -> list[LearningEvent]:
    """Collapse events with identical dedup keys, keeping highest confidence.

    Order is preserved by first appearance. Events with different keys are all
    retained.
    """
    best: dict[tuple[str, str, str, str | None, str | None], LearningEvent] = {}
    order: list[tuple[str, str, str, str | None, str | None]] = []
    for event in events:
        key = event.dedup_key()
        if key not in best:
            best[key] = event
            order.append(key)
        elif event.confidence > best[key].confidence:
            best[key] = event
    return [best[key] for key in order]
