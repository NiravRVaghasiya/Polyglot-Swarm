"""Adaptive difficulty engine.

Uses the Evaluator's per-turn difficulty signal (``too_easy`` / ``appropriate``
/ ``too_hard``) to nudge the effective CEFR level up or down between turns, and
translates the current level into concrete guidance for the Conversation Agent
(speed, sentence complexity, idiom use). This keeps the conversation in the
learner's zone of proximal development instead of staying at a fixed level.

The step is conservative: one sub-level at a time, clamped to A1–C2. It reads
the difficulty from ``state["evaluation"]`` (set by the Evaluator) so it runs
after the evaluator in the turn.
"""

from __future__ import annotations

from typing import Any

from src.agents.difficulty_signals import assess_difficulty, combine, extract_signals
from src.orchestrator.state import LearnerState

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

# How the Conversation Agent should behave at each level.
_LEVEL_GUIDANCE = {
    "A1": "Speak very slowly with short, simple sentences and basic vocabulary.",
    "A2": "Speak slowly, offer choices, accept short answers, avoid idioms.",
    "B1": "Speak at a normal pace with follow-up questions and common expressions.",
    "B2": "Speak at natural speed, use some idioms and more complex sentences.",
    "C1": "Speak naturally with idioms, nuance, and cultural references.",
    "C2": "Speak as with a native peer — full speed, idioms, subtlety.",
}


def _step_level(level: str, direction: int) -> str:
    """Move a CEFR level up (+1) or down (-1), clamped to the valid range."""
    try:
        idx = CEFR_ORDER.index(level)
    except ValueError:
        idx = 1  # default to A2 if unknown
    idx = max(0, min(len(CEFR_ORDER) - 1, idx + direction))
    return CEFR_ORDER[idx]


def next_level(current_level: str, difficulty: str) -> str:
    """Compute the next CEFR level from the current level + difficulty signal.

    - ``too_hard``  -> step down (make it easier)
    - ``too_easy``  -> step up (make it harder)
    - anything else -> unchanged
    """
    if difficulty == "too_hard":
        return _step_level(current_level, -1)
    if difficulty == "too_easy":
        return _step_level(current_level, +1)
    return current_level


def guidance_for_level(level: str) -> str:
    """Return Conversation-Agent behavior guidance for a CEFR level."""
    return _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE["A2"])


def adaptive_node(state: LearnerState) -> dict[str, Any]:
    """Adjust the session's effective difficulty from multiple signals.

    Phase 14: rather than reacting to a single "more correct -> harder" rule,
    this blends the Evaluator's per-turn difficulty signal with a multi-signal
    controller (accuracy, lexical diversity, response length, repair frequency,
    fatigue — see :mod:`src.agents.difficulty_signals`). The combined verdict
    nudges the effective CEFR level, and the corresponding guidance is injected
    into ``current_scenario`` for the next Conversation turn.

    Returns ``{"cefr_level", "current_scenario"}`` — the contract is unchanged;
    ``current_scenario`` also carries ``difficulty_signals`` for observability.
    """
    evaluation = state.get("evaluation") or {}
    evaluator_signal = evaluation.get("difficulty_assessment", "appropriate")
    current = state.get("cefr_level", "A2")

    signals = extract_signals(dict(state))
    controller_signal = assess_difficulty(signals)
    difficulty = combine(evaluator_signal, controller_signal)

    new_level = next_level(current, difficulty)

    scenario = dict(state.get("current_scenario") or {})
    scenario["difficulty_guidance"] = guidance_for_level(new_level)
    scenario["difficulty_signals"] = signals.as_dict()

    return {"cefr_level": new_level, "current_scenario": scenario}
