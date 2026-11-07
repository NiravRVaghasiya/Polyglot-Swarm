"""Retention: FSRS memory states replayed from demonstrated recall (ADR-0033).

FSRS still schedules vocabulary reviews (:mod:`src.agents.srs`); nothing here
changes a live card. This module derives a *read-only* FSRS memory state for
every item that has graded retrieval evidence:

- a word (``item_id`` of vocabulary evidence);
- a grammar construction (its objective).

Each derived state is built by replaying that evidence through the same FSRS
scheduler in time order. This gives the planner one retention view for both,
with the rules the scheduler should have followed:

- **Exposure is not recall.** Exposure-only evidence (a word met in the
  tutor's reply, an ``abstain``) is never replayed as a review.
- **Recognition is not production.** A successful recognition (choosing or
  understanding the word) is rated ``Hard``. A successful independent
  production is rated ``Good``, or the learner's own rating when the review UI
  recorded one. A failure is ``Again``.
- **Correlated judgments count once.** Duplicate fingerprints and judgments
  sharing a ``correlation_id`` are one review.
- **Repeated failures are tracked.** Consecutive failures and lapses (a
  failure after a success) mark an item as a *leech*. Re-drilling a leech the
  same way rarely helps, so the planner remediates it instead.

The result is a pure function of the evidence and ``now``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fsrs import Card, Rating, Scheduler

_SCHEDULER = Scheduler()

#: Consecutive failures / lapses that make an item a leech.
LEECH_CONSECUTIVE_FAILURES = 3
LEECH_LAPSES = 4
#: Retrievability below which a demonstrated item needs review.
REVIEW_THRESHOLD = 0.85

_GRADED = {"correct": True, "incorrect": False, "produced": True, "observed": True}
_EXPOSURE_TYPES = frozenset({"VOCAB_OBSERVED", "TURN_COMPLETED"})


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def retrieval_mode(row: dict[str, Any]) -> str:
    """``production`` or ``recognition`` for a graded retrieval row."""
    sub = str(row.get("subskill") or "").lower()
    if sub in ("recognition", "listening"):
        return "recognition"
    if row.get("event_type") == "REVIEW_RESULT" and sub not in ("production", "spelling"):
        # Legacy review rows recorded no mode: the old review was a recall cue
        # answered by the learner, i.e. recognition-level evidence at best.
        return "recognition"
    return "production"


def rating_for(mode: str, correct: bool, self_rating: int | None = None) -> Rating:
    """The FSRS rating a retrieval outcome deserves (see module docstring)."""
    if not correct:
        return Rating.Again
    if mode == "recognition":
        return Rating.Hard
    if self_rating in (2, 3, 4):
        return Rating(self_rating)
    return Rating.Good


def item_key(row: dict[str, Any]) -> str | None:
    """The memory item a row is about: ``vocabulary:<word>`` or ``grammar.<c>``."""
    skill = row.get("skill")
    if skill == "vocabulary" and row.get("item_id"):
        return f"vocabulary:{str(row['item_id']).strip().lower()}"
    if skill == "grammar":
        objective = row.get("objective_id") or (
            f"grammar.{row['subskill']}" if row.get("subskill") else None
        )
        return str(objective) if objective else None
    return None


@dataclass
class MemoryState:
    """Derived retention state of one item."""

    key: str
    reviews: int = 0
    successes: int = 0
    lapses: int = 0
    consecutive_failures: int = 0
    recognition_successes: int = 0
    production_successes: int = 0
    exposures: int = 0
    last_review: str | None = None
    card: dict[str, Any] | None = None
    retrievability: float | None = None
    due: str | None = None
    event_ids: list[str] = field(default_factory=list)

    @property
    def demonstrated(self) -> bool:
        """At least one successful retrieval (exposure never counts)."""
        return self.successes > 0

    @property
    def leech(self) -> bool:
        return (
            self.consecutive_failures >= LEECH_CONSECUTIVE_FAILURES or self.lapses >= LEECH_LAPSES
        )

    @property
    def forgetting_risk(self) -> float | None:
        """``1 - retrievability``; ``None`` until something was retrieved."""
        return None if self.retrievability is None else 1.0 - self.retrievability

    @property
    def needs_review(self) -> bool:
        return (
            self.demonstrated
            and self.retrievability is not None
            and self.retrievability < REVIEW_THRESHOLD
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "reviews": self.reviews,
            "successes": self.successes,
            "lapses": self.lapses,
            "consecutive_failures": self.consecutive_failures,
            "recognition_successes": self.recognition_successes,
            "production_successes": self.production_successes,
            "exposures": self.exposures,
            "demonstrated": self.demonstrated,
            "leech": self.leech,
            "last_review": self.last_review,
            "retrievability": None
            if self.retrievability is None
            else round(self.retrievability, 4),
            "forgetting_risk": None
            if self.forgetting_risk is None
            else round(self.forgetting_risk, 4),
            "due": self.due,
            "event_ids": list(self.event_ids),
        }


def replay_memory(rows: list[dict[str, Any]], now: datetime) -> dict[str, MemoryState]:
    """Replay graded retrieval evidence through FSRS; return states by item key.

    Only rows created at or before ``now`` are used (no future leakage).
    """
    ordered = sorted(
        (r for r in rows if _parse(r.get("created_at")) is not None),
        key=lambda r: (str(r.get("created_at")), str(r.get("event_id") or "")),
    )
    states: dict[str, MemoryState] = {}
    cards: dict[str, Card] = {}
    seen_groups: set[str] = set()
    for row in ordered:
        ts = _parse(row.get("created_at"))
        assert ts is not None
        if ts > now:
            continue
        key = item_key(row)
        if key is None:
            continue
        state = states.setdefault(key, MemoryState(key=key))
        assessment = str(row.get("assessment") or "").lower()
        if (
            row.get("event_type") in _EXPOSURE_TYPES
            or assessment in ("exposed", "abstain")
            or str(row.get("subskill") or "") == "exposure"
        ):
            state.exposures += 1
            continue
        if assessment not in _GRADED:
            continue
        group = (
            f"c:{row['correlation_id']}|{key}"
            if row.get("correlation_id")
            else f"f:{row.get('fingerprint') or row.get('event_id')}"
        )
        if group in seen_groups:
            continue
        seen_groups.add(group)
        correct = _GRADED[assessment]
        mode = retrieval_mode(row)
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        self_rating = payload.get("rating") if isinstance(payload, dict) else None
        rating = rating_for(mode, correct, self_rating if isinstance(self_rating, int) else None)
        card = cards.get(key) or Card(due=ts)
        card, _ = _SCHEDULER.review_card(card, rating, ts)
        cards[key] = card
        state.reviews += 1
        state.event_ids.append(str(row.get("event_id") or ""))
        state.last_review = ts.isoformat()
        if correct:
            state.successes += 1
            state.consecutive_failures = 0
            if mode == "recognition":
                state.recognition_successes += 1
            else:
                state.production_successes += 1
        else:
            if state.successes > 0:
                state.lapses += 1
            state.consecutive_failures += 1
    for key, card in cards.items():
        state = states[key]
        state.card = dict(card.to_dict())
        state.retrievability = float(_SCHEDULER.get_card_retrievability(card, now))
        state.due = card.due.isoformat()
    return states


def live_retrievability(card_state: dict[str, Any] | None, now: datetime) -> float | None:
    """Retrievability of a live FSRS card (from the vocabulary store), if any.

    A card that has never been reviewed has no memory to retrieve: ``None``.
    """
    if not card_state:
        return None
    try:
        card = Card.from_dict(card_state)  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return None
    if card.last_review is None or card.stability is None:
        return None
    return float(_SCHEDULER.get_card_retrievability(card, now))
