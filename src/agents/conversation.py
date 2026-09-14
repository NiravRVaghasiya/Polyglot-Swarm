"""Conversation Agent — simulates a native speaker in scenario-based dialogues.

This agent:
- Maintains a persona (waiter, landlord, doctor, etc.)
- Adapts language complexity to user's CEFR level
- Never breaks character during the conversation
- Naturally drives toward scenario objectives
"""

from typing import Any

from src.llm.factory import get_provider
from src.llm.provider import Message
from src.orchestrator.state import LearnerState

SYSTEM_PROMPT_TEMPLATE = """You are {persona_name}, a {persona_role} in {location}.
You are having a natural conversation in {language}.

Personality: {personality}

RULES:
- Stay in character at ALL times
- Speak ONLY in {language} (never use English unless the user explicitly asks)
- Adjust your vocabulary complexity to CEFR level {cefr_level}
- Difficulty guidance: {difficulty_guidance}
- Keep responses to 1-3 sentences (natural conversation length)
- Ask follow-up questions to keep the dialogue going
- If the user makes a grammar mistake, do NOT correct them — just continue naturally
- Naturally guide toward these scenario objectives: {objectives}

Current context: {context}
"""


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

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        persona_name=persona.get("name", "Ana"),
        persona_role=persona.get("role", "friendly local"),
        location=scenario.get("location", "a city center"),
        language=language_name,
        personality=persona.get("personality", "warm and patient"),
        cefr_level=state.get("cefr_level", "A2"),
        difficulty_guidance=scenario.get(
            "difficulty_guidance", "Match the learner's level."
        ),
        objectives=", ".join(scenario.get("objectives", ["have a natural conversation"])),
        context=scenario.get("context", "casual encounter"),
    )

    # Build message history for the LLM
    messages = [Message("system", system_prompt)]

    for msg in state.get("messages", []):
        if msg["role"] in ("user", "assistant"):
            messages.append(Message(msg["role"], msg["content"]))

    # Add current user input
    user_input = state.get("last_user_input", "")
    if user_input:
        messages.append(Message("user", user_input))

    # Call LLM via the primary (quality) tier with failover.
    provider = get_provider("primary")
    reply = await provider.generate(messages, temperature=0.8, max_tokens=300)

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
