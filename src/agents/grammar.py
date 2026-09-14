"""Grammar Agent — silent error detection and correction.

This agent:
- Analyzes user input for grammatical errors
- Does NOT interrupt the conversation flow
- Categorizes errors by type and severity
- Builds a persistent error profile for the learner
- Surfaces corrections at the end of the session
"""

from typing import Any

from src.llm.factory import get_provider
from src.llm.provider import Message
from src.orchestrator.state import GrammarError, LearnerState

GRAMMAR_PROMPT = """You are an expert {language} grammar analyzer.

Analyze the following text written by a {cefr_level}-level learner of {language}.
Identify ALL grammatical errors.

For each error, provide:
1. original: the exact incorrect text
2. correction: the corrected version
3. rule: short rule name (e.g., "ser_vs_estar", "gender_agreement", "case_error")
4. explanation: brief explanation in English
5. severity: "minor" (typo/accent), "moderate" (grammar pattern), "critical" (meaning changes)

If there are NO errors, return an empty list.

Respond in valid JSON format:
{{"errors": [{{"original": "...", "correction": "...", "rule": "...",
"explanation": "...", "severity": "..."}}]}}

Known weaknesses for this learner: {weaknesses}

Text to analyze:
"{user_text}"
"""


async def grammar_node(state: LearnerState) -> dict[str, Any]:
    """Detect grammar errors in the user's latest input.

    Runs silently — does not produce user-facing output.
    Errors are stored in state for end-of-session report.

    Args:
        state: Current LearnerState.

    Returns:
        State update with detected grammar errors.
    """
    user_input = state.get("last_user_input", "")

    if not user_input or len(user_input.strip()) < 3:
        return {"grammar_errors": []}

    language_name = state["language"]  # User provides full language name

    prompt = GRAMMAR_PROMPT.format(
        language=language_name,
        cefr_level=state.get("cefr_level", "A2"),
        weaknesses=", ".join(state.get("grammar_weaknesses", [])) or "none identified yet",
        user_text=user_input,
    )

    # Use fast LLM tier for grammar checking (latency-sensitive), with failover.
    provider = get_provider("fast")
    response_text = await provider.generate(
        [
            Message("system", "You are a precise grammar analysis tool. Respond only in JSON."),
            Message("user", prompt),
        ],
        temperature=0.0,  # Deterministic for grammar analysis
        max_tokens=500,
        json_mode=True,
    )

    # Parse errors from response
    errors = _parse_grammar_response(response_text)

    return {"grammar_errors": state.get("grammar_errors", []) + errors}


def _parse_grammar_response(response_text: str) -> list[GrammarError]:
    """Parse LLM JSON response into GrammarError objects.

    Handles malformed JSON gracefully.
    """
    import json

    try:
        # Try to extract JSON from the response
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        data = json.loads(text)
        errors = data.get("errors", [])

        return [
            GrammarError(
                original=e.get("original", ""),
                correction=e.get("correction", ""),
                rule=e.get("rule", "unknown"),
                explanation=e.get("explanation", ""),
                severity=e.get("severity", "moderate"),
            )
            for e in errors
            if e.get("original")  # Skip empty entries
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
