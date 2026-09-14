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
    }


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens from text (accent-preserving, punctuation-stripped)."""
    return set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def _conversation_tokens(messages: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for msg in messages:
        tokens |= _tokenize(str(msg.get("content", "")))
    return tokens


def objective_status(
    scenario: Scenario, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
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


def target_vocab_coverage(
    scenario: Scenario, messages: list[dict[str, Any]]
) -> float:
    """Fraction of all objectives' required vocab that appeared in conversation."""
    all_required = {
        v.lower() for obj in scenario.objectives for v in obj.required_vocab
    }
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

    return {
        "objectives_completed": all_done,
        "objectives_ok": objectives_ok,
        "vocab_coverage": coverage,
        "vocab_coverage_ok": coverage_ok,
        "grammar_error_rate": grammar_error_rate,
        "grammar_ok": grammar_ok,
        "passed": objectives_ok and coverage_ok and grammar_ok,
    }
