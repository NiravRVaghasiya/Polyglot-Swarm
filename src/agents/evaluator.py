"""Evaluator Agent — QA layer for all agent outputs.

Based on the WikiHowAgent (Sep 2025) Teacher + Learner + Manager + Evaluator
pattern: a dedicated evaluator outperforms agent self-assessment. It runs AFTER
Grammar, Vocabulary, and Cultural agents (graph fan-in) and:

- Validates grammar corrections and drops false positives (correct sentences
  wrongly flagged, or acceptable given dialect/register/context).
- Assesses whether conversation difficulty matches the learner's level.
- Resolves conflicts between agents (e.g. Grammar wants formal, Cultural says
  informal is fine here) via pedagogical notes.

A cheap heuristic difficulty check runs first as a fast pre-check; the LLM
provides the nuanced validation and conflict resolution.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render
from src.llm.provider import Message
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.evaluator")


async def evaluator_node(state: LearnerState) -> dict[str, Any]:
    """Quality-check outputs from the other agents and apply overrides.

    Returns a state update containing:
    - ``evaluation``: the structured evaluation result.
    - ``grammar_errors``: the grammar list with validated false positives
      removed (so the end-of-session report and persistence only keep real
      errors).
    """
    grammar_errors = state.get("grammar_errors", [])
    cultural_notes = state.get("cultural_notes", [])
    user_input = state.get("last_user_input", "")

    heuristic_difficulty = _assess_difficulty(state)

    # Nothing to validate and no input to judge — return the fast heuristic only.
    if not user_input or (not grammar_errors and not cultural_notes):
        evaluation = {
            "grammar_errors_validated": len(grammar_errors),
            "difficulty_assessment": heuristic_difficulty,
            "overrides": [],
            "notes": [],
        }
        return {"evaluation": evaluation, "grammar_errors": grammar_errors}

    prompt = render(
        "evaluator.jinja2",
        language=state["language"],
        cefr_level=state.get("cefr_level", "A2"),
        user_text=user_input,
        grammar_errors=grammar_errors,
        cultural_notes=cultural_notes,
    )

    provider = get_provider("fast")
    try:
        response_text = await provider.generate(
            [
                Message("system", "You are a precise QA evaluator. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.0,
            max_tokens=500,
            json_mode=True,
        )
        parsed = _parse_evaluation(response_text)
    except Exception as exc:  # noqa: BLE001 - QA must never break the turn
        logger.warning("Evaluator LLM call failed: %s", exc)
        parsed = {"overrides": [], "adjustments": {}, "notes": []}

    override_indices = _valid_override_indices(parsed.get("overrides", []), len(grammar_errors))
    validated_errors = [
        e for i, e in enumerate(grammar_errors) if i not in override_indices
    ]

    difficulty = parsed.get("adjustments", {}).get("difficulty", heuristic_difficulty)

    evaluation = {
        "grammar_errors_validated": len(validated_errors),
        "grammar_errors_overridden": len(override_indices),
        "difficulty_assessment": difficulty,
        "overrides": sorted(override_indices),
        "notes": [n for n in parsed.get("notes", []) if isinstance(n, str)],
    }

    return {"evaluation": evaluation, "grammar_errors": validated_errors}


def _valid_override_indices(raw: Any, count: int) -> set[int]:
    """Coerce the LLM's override list into a set of valid in-range indices."""
    indices: set[int] = set()
    if not isinstance(raw, list):
        return indices
    for item in raw:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < count:
            indices.add(idx)
    return indices


def _parse_evaluation(response_text: str) -> dict[str, Any]:
    """Parse the evaluator LLM JSON response, tolerating code fences."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        if not isinstance(data, dict):
            return {"overrides": [], "adjustments": {}, "notes": []}
        return data
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return {"overrides": [], "adjustments": {}, "notes": []}


def _assess_difficulty(state: LearnerState) -> str:
    """Fast heuristic: is the current session difficulty appropriate?

    Returns "too_easy", "appropriate", or "too_hard" based on error rate.
    """
    errors = state.get("grammar_errors", [])
    turn_count = state.get("turn_count", 0)

    if turn_count == 0:
        return "appropriate"

    error_rate = len(errors) / max(turn_count, 1)

    if error_rate > 0.5:
        return "too_hard"
    if error_rate < 0.05 and turn_count > 3:
        return "too_easy"
    return "appropriate"
