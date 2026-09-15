"""Grammar Agent — silent, taxonomy-aware error detection and correction.

This agent:
- Analyzes user input for grammatical deviations.
- Does NOT interrupt the conversation flow.
- Classifies each deviation on a taxonomy (wrong / awkward / unusual / regional
  / formal / informal / acceptable) rather than treating every deviation as an
  error, and attaches a calibrated confidence — so the tutor does not
  "correct" perfectly valid regional or informal language (Phase 4).
- Only genuine errors (``wrong``/``awkward``) are surfaced and persisted; other
  classifications are recognized and dropped so they never reach the report.
- Builds a persistent error profile for the learner.
- Surfaces corrections at the end of the session.
"""

from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.llm.schemas import GrammarAnalysis, GrammarErrorModel
from src.orchestrator.state import GrammarError, LearnerState

#: Minimum confidence for a genuine error to be surfaced. Below this the agent
#: abstains (drops it) rather than risk a false correction.
_MIN_ERROR_CONFIDENCE = 0.5


async def grammar_node(state: LearnerState) -> dict[str, Any]:
    """Detect and classify grammar deviations in the user's latest input.

    Runs silently. Only genuine, confident errors are kept; acceptable variants
    (regional/informal/acceptable) and low-confidence flags are dropped.
    """
    user_input = state.get("last_user_input", "")

    if not user_input or len(user_input.strip()) < 3:
        return {"grammar_errors": []}

    language_name = state["language"]

    prompt = str(
        render_prompt(
            "grammar",
            language=language_name,
            cefr_level=state.get("cefr_level", "A2"),
            weaknesses=", ".join(state.get("grammar_weaknesses", [])) or "none identified yet",
            user_text=user_input,
        )
    )

    # Fast tier, deterministic, structured output validated against a schema.
    provider = get_provider("fast")
    analysis = await provider.generate_structured(
        [
            Message("system", "You are a precise grammar analysis tool. Respond only in JSON."),
            Message("user", prompt),
        ],
        GrammarAnalysis,
        temperature=0.0,
        max_tokens=700,
    )

    errors = _select_errors(analysis)

    return {"grammar_errors": state.get("grammar_errors", []) + errors}


def _select_errors(analysis: GrammarAnalysis | None) -> list[GrammarError]:
    """Turn a validated analysis into the genuine, confident errors to surface.

    Filters out acceptable variation (regional/informal/acceptable/...) and
    low-confidence flags, then maps each surviving model into the backward
    -compatible :class:`GrammarError` dict (legacy keys preserved).
    """
    if analysis is None:
        return []

    kept: list[GrammarError] = []
    for e in analysis.errors:
        if not e.original:
            continue
        if not e.is_error():
            continue  # acceptable variation — do not correct
        if e.confidence < _MIN_ERROR_CONFIDENCE:
            continue  # abstain rather than risk a false correction
        kept.append(_to_grammar_error(e))
    return kept


def _to_grammar_error(model: GrammarErrorModel) -> GrammarError:
    """Map a validated model to the legacy-compatible GrammarError dict."""
    construction = model.construction or model.rule
    return GrammarError(
        original=model.original,
        correction=model.correction,
        rule=model.rule if model.rule != "unknown" else construction,
        explanation=model.explanation,
        severity=model.severity,
        classification=model.classification,
        construction=construction,
        confidence=model.confidence,
        alternatives=model.alternatives,
    )
