"""Conversation Agent — simulates a native speaker in scenario-based dialogues.

This agent:
- Maintains a persona (waiter, landlord, doctor, etc.)
- Adapts language complexity to user's CEFR level
- Never breaks character during the conversation
- Naturally drives toward scenario objectives
"""

import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.orchestrator.state import LearnerState
from src.safety.injection import UNTRUSTED_DATA_NOTICE, wrap_untrusted
from src.safety.roleplay import disclaimer_for_role

logger = logging.getLogger("polyglot.conversation")

# Phase 23 (production reliability): the graph has no turn boundary until the
# conversation node produces a reply — so if every provider in the routing
# chain is down (retries and failover both exhausted), this used to crash the
# whole turn with an unhandled exception. A total-outage turn is degraded
# instead: the learner still gets a reply (in-character, generic) rather than
# an error, and the turn completes normally so the session can continue and
# the next turn gets a fresh chance at the provider chain.
_FALLBACK_REPLY_BY_LANGUAGE = {
    "spanish": "Disculpa, no te escuché bien. ¿Puedes repetirlo?",
    "polish": "Przepraszam, nie usłyszałem cię dobrze. Czy możesz powtórzyć?",
    "italian": "Scusa, non ti ho sentito bene. Puoi ripetere?",
}
_DEFAULT_FALLBACK_REPLY = "Sorry, I didn't catch that. Could you say it again?"


def _fallback_reply(language: str) -> str:
    """A generic, in-character reply used when the whole provider chain fails.

    Framed as "I didn't hear you" rather than a technical error message, so a
    total LLM outage still reads as a plausible in-scenario line instead of
    breaking immersion (or leaking infrastructure details) mid role-play.
    """
    return _FALLBACK_REPLY_BY_LANGUAGE.get(language.strip().lower(), _DEFAULT_FALLBACK_REPLY)


# Phase 22 cost/latency: the plan explicitly says not to send the learner's
# entire history to the LLM. Before this, every turn re-sent the full
# transcript since session start — cost and latency both grow unboundedly
# with session length, for a benefit (long-range context) conversational
# role-play rarely needs beyond the last several exchanges. Capped at recent
# turns; the persona/objectives/CEFR level (the durable context) already
# ride in the system prompt every turn regardless of history length, so
# nothing about *who* the persona is or *what* they're steering toward is
# lost by trimming *what was said*.
MAX_HISTORY_MESSAGES = 20


def _windowed_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return at most the most recent :data:`MAX_HISTORY_MESSAGES` turns."""
    if len(messages) <= MAX_HISTORY_MESSAGES:
        return messages
    return messages[-MAX_HISTORY_MESSAGES:]


# Phase 20: scenario definitions (persona/objectives/location/...) are
# free-text — today shipped as version-controlled YAML, but architecturally
# no different from a future community-contributed or user-uploaded scenario.
# The plan's rule ("never allow retrieved content to become system
# instructions") applies here just as it does to ingested external content:
# the SCENARIO block is delimited and explicitly marked as data (see
# _build_scenario_block), so a scenario field cannot smuggle an instruction
# into this system prompt merely by being interpolated into it. The RULES
# section (fixed, not scenario-derived) remains the actual governing
# instructions. The prompt template itself now lives in the versioned prompt
# registry (Gate B) as "conversation" / conversation_v1.jinja2.


def _build_scenario_block(scenario: dict[str, Any]) -> str:
    """Render the scenario's free-text fields as an explicitly untrusted block.

    Everything scenario-derived (persona name/role/personality, location,
    objectives) is plain data describing the character to play, not a set of
    instructions from the system designer — so it is delimited the same way
    :mod:`src.agents.ingestion` delimits fetched external content, per the
    plan's rule that retrieved/external content must never become system
    instructions.
    """
    persona = scenario.get("persona", {}) or {}
    lines = [
        f"Character: {persona.get('name', 'Ana')}",
        f"Role: {persona.get('role', 'friendly local')}",
        f"Personality: {persona.get('personality', 'warm and patient')}",
        f"Location: {scenario.get('location', 'a city center')}",
        f"Context: {scenario.get('context', 'casual encounter')}",
        "Objectives to work toward: "
        + ", ".join(scenario.get("objectives", ["have a natural conversation"])),
    ]
    return wrap_untrusted("\n".join(lines), label="SCENARIO")


def _pedagogical_steering(scenario: dict[str, Any]) -> str:
    """Build the optional steering block that makes the persona create
    opportunities for the scenario's target skills (Phase 13).

    Returns an empty string when the scenario declares no targets, so a plain
    conversation prompt is unchanged.
    """
    lines: list[str] = []
    grammar = scenario.get("target_grammar") or []
    vocab = scenario.get("target_vocabulary") or []
    functions = scenario.get("target_functions") or []
    constraints = scenario.get("constraints") or []

    if grammar:
        lines.append(
            "- Steer the dialogue so the learner naturally needs these grammar "
            f"structures (do NOT name them): {', '.join(grammar)}"
        )
    if vocab:
        lines.append(f"- Create situations where these words come up: {', '.join(vocab[:15])}")
    if functions:
        lines.append(f"- Prompt the learner to perform these functions: {', '.join(functions)}")
    if constraints:
        lines.append(f"- Honor these constraints: {'; '.join(constraints)}")

    if not lines:
        return ""
    return "PEDAGOGICAL STEERING (stay subtle and in character):\n" + "\n".join(lines) + "\n"


async def conversation_node(state: LearnerState) -> dict[str, Any]:
    """Generate a conversational response in the target language.

    Uses the configured persona and adapts to user's CEFR level.

    Args:
        state: Current LearnerState.

    Returns:
        State update with the agent's response added to messages.
    """
    # User provides full language name (e.g., "Spanish", "Japanese").
    language_name = state["language"]

    scenario = state.get("current_scenario", {}) or {}
    persona = scenario.get("persona", {})

    system_prompt = str(
        render_prompt(
            "conversation",
            language=language_name,
            scenario_block=_build_scenario_block(scenario),
            untrusted_data_notice=UNTRUSTED_DATA_NOTICE,
            cefr_level=state.get("cefr_level", "A2"),
            difficulty_guidance=scenario.get("difficulty_guidance", "Match the learner's level."),
            pedagogical_steering=_pedagogical_steering(scenario),
            role_disclaimer=disclaimer_for_role(persona.get("role", "")),
        )
    )

    # Build message history for the LLM, windowed to the most recent turns
    # (Phase 22) rather than the full transcript since session start.
    messages = [Message("system", system_prompt)]

    for msg in _windowed_history(state.get("messages", [])):
        if msg["role"] in ("user", "assistant"):
            messages.append(Message(msg["role"], msg["content"]))

    # Add current user input
    user_input = state.get("last_user_input", "")
    if user_input:
        messages.append(Message("user", user_input))

    # Call LLM via the primary (quality) tier with retry/failover (Phase 22/23).
    # If the ENTIRE chain is exhausted (every provider unavailable, circuit-broken,
    # or failed after its retries), degrade to a canned in-character reply
    # rather than letting the exception crash the turn.
    provider = get_provider("primary")
    try:
        reply = await provider.generate(messages, temperature=0.8, max_tokens=300)
    except Exception as exc:  # noqa: BLE001 - total provider outage must not crash the turn
        logger.error("All LLM providers failed for conversation turn: %s", exc)
        reply = _fallback_reply(language_name)

    # Update state
    new_messages = []
    if user_input:
        new_messages.append({"role": "user", "content": user_input})
    new_messages.append({"role": "assistant", "content": reply})

    return {
        "messages": new_messages,
        "agent_response": reply,
        "turn_count": state.get("turn_count", 0) + 1,
    }
