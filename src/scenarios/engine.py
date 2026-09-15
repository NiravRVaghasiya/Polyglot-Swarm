"""Scenario engine — runs a scenario within a learning session.

Responsibilities:
- Build the ``current_scenario`` dict the Conversation Agent consumes (persona,
  location, objectives, context, difficulty guidance for the learner's level).
- Track objective completion across turns: an objective is met once all of its
  ``required_vocab`` has appeared in the conversation.
- Evaluate the scenario's success criteria (objectives completed, target-vocab
  coverage, grammar error rate).
"""

from __future__ import annotations

import re
from typing import Any

from src.scenarios.loader import Scenario


def build_scenario_context(scenario: Scenario, cefr_level: str) -> dict[str, Any]:
    """Build the ``current_scenario`` dict for a session from a Scenario.

    The shape matches what the Conversation Agent reads: ``persona`` (dict with
    name/role/personality), ``location``, ``objectives`` (list of description
    strings), plus scenario metadata and per-level difficulty guidance.
    """
    return {
        "scenario_id": scenario.id,
        "title": scenario.title,
        "persona": {
            "name": scenario.persona.name,
            "role": scenario.persona.role,
            "personality": scenario.persona.personality,
            "dialect": scenario.persona.dialect,
        },
        "location": scenario.location,
        "objectives": [obj.description for obj in scenario.objectives],
        "context": scenario.title,
        "opening_line": scenario.opening_line,
        "difficulty_guidance": scenario.scaling_for(cefr_level),
        # Kept for objective tracking / success evaluation.
        "objective_specs": [
            {"id": o.id, "description": o.description, "required_vocab": o.required_vocab}
            for o in scenario.objectives
        ],
        "success_criteria": scenario.success_criteria.model_dump(),
        # Phase 13: pedagogical targets the persona should create opportunities
        # for. These steer the Conversation Agent (see conversation.py).
        "target_grammar": list(scenario.target_grammar),
        "target_vocabulary": scenario.all_target_vocabulary(),
        "target_functions": list(scenario.target_functions),
        "constraints": list(scenario.constraints),
        "failure_conditions": list(scenario.failure_conditions),
        "transfer_opportunities": list(scenario.transfer_opportunities),
    }


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens from text (accent-preserving, punctuation-stripped)."""
    return set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def _conversation_tokens(messages: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for msg in messages:
        tokens |= _tokenize(str(msg.get("content", "")))
    return tokens


def objective_status(scenario: Scenario, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return each objective with a completion flag.

    An objective is complete when every word in its ``required_vocab`` has
    appeared somewhere in the conversation. Objectives with no required vocab
    are treated as complete once any conversation has occurred.
    """
    tokens = _conversation_tokens(messages)
    status = []
    for obj in scenario.objectives:
        required = {v.lower() for v in obj.required_vocab}
        completed = bool(tokens) and required.issubset(tokens) if required else bool(tokens)
        status.append(
            {
                "id": obj.id,
                "description": obj.description,
                "required_vocab": obj.required_vocab,
                "completed": completed,
            }
        )
    return status


def target_vocab_coverage(scenario: Scenario, messages: list[dict[str, Any]]) -> float:
    """Fraction of all objectives' required vocab that appeared in conversation."""
    all_required = {v.lower() for obj in scenario.objectives for v in obj.required_vocab}
    if not all_required:
        return 1.0
    used = all_required & _conversation_tokens(messages)
    return len(used) / len(all_required)


def evaluate_success(
    scenario: Scenario,
    messages: list[dict[str, Any]],
    *,
    grammar_error_rate: float = 0.0,
) -> dict[str, Any]:
    """Evaluate the scenario's success criteria against the conversation.

    Returns a dict with per-criterion booleans and an overall ``passed`` flag.
    """
    criteria = scenario.success_criteria
    status = objective_status(scenario, messages)
    all_done = all(s["completed"] for s in status) if status else False
    coverage = target_vocab_coverage(scenario, messages)

    objectives_ok = all_done if criteria.all_objectives_completed else True
    coverage_ok = coverage >= criteria.target_vocabulary_used_min
    grammar_ok = grammar_error_rate <= criteria.grammar_error_rate_max

    failed, failure_reasons = _evaluate_failure(scenario, messages)

    return {
        "objectives_completed": all_done,
        "objectives_ok": objectives_ok,
        "vocab_coverage": coverage,
        "vocab_coverage_ok": coverage_ok,
        "grammar_error_rate": grammar_error_rate,
        "grammar_ok": grammar_ok,
        "failed": failed,
        "failure_reasons": failure_reasons,
        # A scenario passes only if criteria are met AND no failure condition hit.
        "passed": objectives_ok and coverage_ok and grammar_ok and not failed,
    }


def _evaluate_failure(scenario: Scenario, messages: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Check the scenario's ``failure_conditions`` against the conversation.

    Deterministic heuristics for the built-in conditions; unknown/free-text
    conditions are ignored here (a future LLM check can handle them). Returns
    ``(failed, reasons)``.
    """
    reasons: list[str] = []
    user_text = " ".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "user"
    ).lower()

    for condition in scenario.failure_conditions:
        cond = condition.lower()
        # "switched to English" / "used English" — crude English detection.
        if ("english" in cond) and _looks_like_english(user_text):
            reasons.append(condition)
        # "gave up" / "abandoned" — an explicit give-up phrase.
        elif ("gave up" in cond or "abandon" in cond) and any(
            p in user_text for p in ("i give up", "no puedo", "nie mogę", "non riesco")
        ):
            reasons.append(condition)
    return (bool(reasons), reasons)


# Common English function words used only for a crude "switched to English" check.
_ENGLISH_MARKERS = {
    "the",
    "and",
    "you",
    "what",
    "where",
    "please",
    "thank",
    "yes",
    "no",
    "want",
    "have",
}


def _looks_like_english(text: str) -> bool:
    """Very rough check: several common English function words present."""
    tokens = _tokenize(text)
    hits = len(tokens & _ENGLISH_MARKERS)
    return hits >= 3
