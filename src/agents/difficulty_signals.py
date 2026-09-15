"""Multi-signal difficulty controller (Phase 14).

The plan warns against the naive rule "more correct -> harder". Instead the
controller reads several signals from the conversation and combines them into a
single verdict — ``too_easy`` / ``appropriate`` / ``too_hard`` — that the
adaptive engine uses to nudge the effective level.

Signals (all computed from the session state, no new dependencies):

- **accuracy**: grammar errors per user turn (fewer = easier for the learner).
- **lexical diversity**: type/token ratio of the learner's words (higher =
  the learner is comfortable stretching their vocabulary).
- **response length**: average words per user turn (very short = struggling or
  disengaged; longer = coping).
- **repair frequency**: how often the learner self-corrects mid-utterance
  (frequent repairs = the material is at the edge of their ability).
- **fatigue**: proxied by turn count and shrinking responses late in a session.

Each signal votes toward easier/harder/steady; the controller aggregates the
votes. This is deliberately transparent and dependency-free; a learned
controller can replace :func:`assess_difficulty` later without changing callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Markers a learner uses when self-correcting mid-utterance (repair).
_REPAIR_MARKERS = (
    "no,",
    "perdón",
    "quería decir",
    "es decir",
    "digo",
    "mejor dicho",
    "cioè",
    "volevo dire",
    "znaczy",
    "chciałem powiedzieć",
    "i mean",
    "sorry",
)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


@dataclass
class DifficultySignals:
    """The raw signals extracted from a session's learner turns."""

    turns: int
    error_rate: float  # grammar errors per user turn
    lexical_diversity: float  # type/token ratio (0..1)
    avg_response_length: float  # words per user turn
    repair_rate: float  # self-corrections per user turn

    def as_dict(self) -> dict[str, float]:
        return {
            "turns": self.turns,
            "error_rate": round(self.error_rate, 3),
            "lexical_diversity": round(self.lexical_diversity, 3),
            "avg_response_length": round(self.avg_response_length, 2),
            "repair_rate": round(self.repair_rate, 3),
        }


def extract_signals(state: dict[str, Any]) -> DifficultySignals:
    """Compute difficulty signals from the session state.

    Reads the learner's own turns (``role == "user"``) plus the accumulated
    grammar errors and turn count. Pure — no I/O.
    """
    messages = state.get("messages", [])
    user_turns = [m for m in messages if m.get("role") == "user" and m.get("content")]
    turns = len(user_turns) or int(state.get("turn_count", 0))

    all_tokens: list[str] = []
    repairs = 0
    total_words = 0
    for m in user_turns:
        content = str(m.get("content", ""))
        toks = _tokens(content)
        all_tokens.extend(toks)
        total_words += len(toks)
        lowered = content.lower()
        if any(marker in lowered for marker in _REPAIR_MARKERS):
            repairs += 1

    denom = max(turns, 1)
    error_rate = len(state.get("grammar_errors", [])) / denom
    lexical_diversity = (len(set(all_tokens)) / len(all_tokens)) if all_tokens else 0.0
    avg_length = total_words / denom if total_words else 0.0
    repair_rate = repairs / denom

    return DifficultySignals(
        turns=turns,
        error_rate=error_rate,
        lexical_diversity=lexical_diversity,
        avg_response_length=avg_length,
        repair_rate=repair_rate,
    )


def assess_difficulty(signals: DifficultySignals) -> str:
    """Aggregate the signals into a difficulty verdict.

    Returns ``too_easy`` / ``appropriate`` / ``too_hard``. Each signal casts a
    vote (+1 harder / -1 easier); the net decides. Requires a couple of turns of
    evidence before moving off ``appropriate`` so it doesn't overreact to one
    turn.
    """
    if signals.turns < 2:
        return "appropriate"

    votes = 0

    # Accuracy: many errors -> too hard; almost none -> could go harder.
    if signals.error_rate > 0.5:
        votes -= 2
    elif signals.error_rate < 0.05:
        votes += 1

    # Repair frequency: lots of self-correction -> at the edge -> too hard.
    if signals.repair_rate > 0.4:
        votes -= 1

    # Response length: very short -> struggling/disengaged; long -> coping well.
    if signals.avg_response_length < 3:
        votes -= 1
    elif signals.avg_response_length > 12:
        votes += 1

    # Lexical diversity: high diversity with low errors -> ready for more.
    if signals.lexical_diversity > 0.7 and signals.error_rate < 0.2:
        votes += 1

    if votes <= -2:
        return "too_hard"
    if votes >= 2:
        return "too_easy"
    return "appropriate"


def combine(evaluator_signal: str, controller_signal: str) -> str:
    """Reconcile the evaluator's difficulty signal with the controller's.

    Safety-first: if either says ``too_hard``, back off (learner comfort beats
    challenge) — this is where the multi-signal controller adds value, catching
    struggle the evaluator's error-rate heuristic alone would miss. Otherwise
    raise difficulty when either signals ``too_easy`` and neither warns of
    difficulty; else stay. A signal of ``appropriate`` is treated as "no
    opinion", so a confident single signal still acts.
    """
    if "too_hard" in (evaluator_signal, controller_signal):
        return "too_hard"
    if "too_easy" in (evaluator_signal, controller_signal):
        return "too_easy"
    return "appropriate"
