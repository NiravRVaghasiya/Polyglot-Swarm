"""Assessment Agent — estimates the learner's CEFR level.

Aggregates signals from the persistent stores (vocabulary breadth, grammar
error rate) and the current session (response length, errors this turn) into a
CEFR band (A1–C2), using the thresholds from the design doc (section 10.2):

| Level | Vocab Size | Response Length |
|-------|------------|-----------------|
| A1    | <500       | 3–8 words       |
| A2    | 500–1000   | 8–15 words      |
| B1    | 1000–2000  | 15–25 words     |
| B2    | 2000–4000  | 25–40 words     |
| C1    | 4000–8000  | 40+ words       |

The estimate is deterministic (no LLM needed): it maps each metric to a band
and takes a conservative (minimum) combined level, so a large vocabulary alone
does not inflate the estimate past what fluency/accuracy support.

This heuristic sets the tutor's **working level** (how hard the tutor's own
language should be), which is an instructional setting, not an assessment. The
learner's assessed CEFR level is the evidence-backed profile in
:mod:`src.assessment.cefr_profile`, which has no default and can report
``insufficient_evidence`` (ADR-0031).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.learner.cefr_bands import CEFR_ORDER
from src.memory import analytics, user_profile, vocabulary_db
from src.orchestrator.state import LearnerState

# (max_vocab_exclusive, level) — first bucket whose bound the vocab is under.
_VOCAB_BANDS = [
    (500, "A1"),
    (1000, "A2"),
    (2000, "B1"),
    (4000, "B2"),
    (8000, "C1"),
]

# (max_avg_words_exclusive, level)
_LENGTH_BANDS = [
    (8, "A1"),
    (15, "A2"),
    (25, "B1"),
    (40, "B2"),
]


@dataclass
class CEFRMetrics:
    """Metrics used to estimate CEFR level."""

    unique_words_used: int
    grammar_error_rate: float  # errors per user turn
    avg_response_length: float  # words per user turn


def _band_from_bins(value: float, bins: list[tuple[int, str]], top: str) -> str:
    for bound, level in bins:
        if value < bound:
            return level
    return top


def _vocab_band(unique_words: int) -> str:
    return _band_from_bins(unique_words, _VOCAB_BANDS, "C2")


def _length_band(avg_len: float) -> str:
    return _band_from_bins(avg_len, _LENGTH_BANDS, "C1")


def _min_level(*levels: str) -> str:
    """Return the lowest CEFR level among the arguments (conservative estimate)."""
    return min(levels, key=lambda lvl: CEFR_ORDER.index(lvl))


def compute_metrics(state: LearnerState) -> CEFRMetrics:
    """Compute CEFR metrics from persisted stores + the current session."""
    user_id = state["user_id"]
    language = state["language"]

    unique_words = vocabulary_db.count_for_user(user_id, language)

    user_turns = [m for m in state.get("messages", []) if m.get("role") == "user"]
    total_words = sum(len(m.get("content", "").split()) for m in user_turns)
    avg_length = total_words / len(user_turns) if user_turns else 0.0

    error_count = len(state.get("grammar_errors", []))
    error_rate = error_count / len(user_turns) if user_turns else 0.0

    return CEFRMetrics(
        unique_words_used=unique_words,
        grammar_error_rate=error_rate,
        avg_response_length=avg_length,
    )


def estimate_cefr(metrics: CEFRMetrics, *, current_level: str = "A2") -> str:
    """Estimate a CEFR band from metrics.

    Combines the vocabulary and response-length bands conservatively (min). A
    high error rate pulls the estimate down by one level (floored at A1). If
    there is no signal yet (no words, no turns) the current level is retained.
    """
    if metrics.unique_words_used == 0 and metrics.avg_response_length == 0.0:
        return current_level

    vocab_level = _vocab_band(metrics.unique_words_used)
    length_level = _length_band(metrics.avg_response_length)
    combined = _min_level(vocab_level, length_level)

    # A high error rate (> 0.5 errors per turn) signals the level is too high.
    if metrics.grammar_error_rate > 0.5:
        idx = max(0, CEFR_ORDER.index(combined) - 1)
        combined = CEFR_ORDER[idx]

    return combined


def has_signal(metrics: CEFRMetrics) -> bool:
    """Whether the session produced anything to estimate a working level from."""
    return not (metrics.unique_words_used == 0 and metrics.avg_response_length == 0.0)


def update_working_level(state: LearnerState) -> str:
    """Re-estimate the tutor's *working level* from this session and persist it.

    The working level is the band the tutor pitches its language at — an
    instructional setting, not an assessment of the learner (ADR-0031; the
    evidence-backed, nullable assessment is the CEFR profile). It is only
    written to the profile and to the session log when the session produced
    a signal, so a learner who has not said anything never gets a recorded
    level. Returns the (possibly unchanged) working level.
    """
    metrics = compute_metrics(state)
    current = state.get("cefr_level") or user_profile.DEFAULT_WORKING_LEVEL
    if not has_signal(metrics):
        return current
    new_level = estimate_cefr(metrics, current_level=current)

    user_id = state["user_id"]
    language = state["language"]
    profile = user_profile.load_profile(user_id)
    updated_cefr = dict(profile.cefr_by_language)
    updated_cefr[language] = new_level
    user_profile.update_profile(user_id, cefr_by_language=updated_cefr)

    # A lightweight session row for the working-level history.
    analytics.log_session(
        user_id,
        language,
        session_type="assessment",
        cefr_estimate=new_level,
    )
    return new_level


def persist_evidence_profile(user_id: str, language: str) -> None:
    """Build and persist the evidence-backed CEFR profile (best-effort)."""
    try:
        from src.assessment.cefr_profile import build_cefr_profile, persist_profile

        persist_profile(user_id, build_cefr_profile(user_id, language))
    except Exception as exc:  # noqa: BLE001 - profiling must not break assessment
        import logging

        logging.getLogger("polyglot.assessment").warning("CEFR profile failed: %s", exc)
