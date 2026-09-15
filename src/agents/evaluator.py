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

from src.evaluation import verifier
from src.evaluation.policies import is_high_impact
from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message, Tier
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

    prompt = str(
        render_prompt(
            "evaluator",
            language=state["language"],
            cefr_level=state.get("cefr_level", "A2"),
            user_text=user_input,
            grammar_errors=grammar_errors,
            cultural_notes=cultural_notes,
        )
    )

    # Phase 22 budget-aware routing: the "fast"/cheap tier is enough to
    # rubber-stamp routine, low-impact flags, but a genuinely high-impact
    # correction (a confident "wrong"/"awkward" call at moderate-or-worse
    # severity — see policies.is_high_impact) is exactly the case where a
    # false positive is most costly to the learner, so it's worth spending
    # the stronger "primary" tier's better judgment. Escalating only when
    # warranted (rather than always using primary) is what keeps the
    # per-turn cost down on the common case.
    tier: Tier = "primary" if any(is_high_impact(dict(e)) for e in grammar_errors) else "fast"
    provider = get_provider(tier)
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
    llm_decisions = _parse_decisions(parsed.get("decisions", []), len(grammar_errors))

    # Phase 9: run the verifier — accept / revise / reject / abstain per error,
    # reconciling grammar-vs-cultural conflicts. Legacy ``overrides`` are honored
    # as forced drops so the existing protocol keeps working.
    outcome = verifier.verify_errors(
        [dict(e) for e in grammar_errors],
        cultural_notes=cultural_notes,
        llm_decisions=llm_decisions,
        override_indices=override_indices,
    )
    validated_errors = outcome.kept
    dropped = sorted(set(outcome.dropped_indices))

    difficulty = parsed.get("adjustments", {}).get("difficulty", heuristic_difficulty)

    evaluation = {
        "grammar_errors_validated": len(validated_errors),
        "grammar_errors_overridden": len(dropped),
        "difficulty_assessment": difficulty,
        "overrides": dropped,
        "notes": [n for n in parsed.get("notes", []) if isinstance(n, str)],
        # Phase 9 additions (observability of the verifier's reasoning).
        "verifier": {
            "decisions": {str(i): d for i, d in outcome.decisions.items()},
            "abstained": outcome.abstained,
            "revised": outcome.revised,
        },
    }

    return {"evaluation": evaluation, "grammar_errors": validated_errors}


def _parse_decisions(raw: Any, count: int) -> dict[int, dict[str, Any]]:
    """Coerce an optional per-error decisions list into an index->decision map.

    Each entry may carry ``index`` (else positional), ``decision``,
    ``confidence``, ``revised`` — the :class:`VerifierDecision` shape.
    """
    out: dict[int, dict[str, Any]] = {}
    if not isinstance(raw, list):
        return out
    for pos, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index", pos))
        except (TypeError, ValueError):
            idx = pos
        if 0 <= idx < count:
            out[idx] = item
    return out


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
