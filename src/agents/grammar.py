"""Grammar Agent — silent, taxonomy-aware error detection and correction.

This agent:
- Analyzes user input for grammatical deviations.
- Does NOT interrupt the conversation flow.
- Classifies each deviation on a taxonomy (wrong / awkward / unusual / regional
  / formal / informal / acceptable) rather than treating every deviation as an
  error, so the tutor does not "correct" perfectly valid regional or informal
  language (Phase 4).
- Calibrates the model's self-reported confidence with the answering model's
  calibration map when one exists (:mod:`src.evaluation.calibration_maps`);
  otherwise the raw confidence is used and the result logged as uncalibrated.
- Only genuine errors (``wrong``/``awkward``) are surfaced and persisted; other
  classifications are recognized and dropped so they never reach the report.
- Builds a persistent error profile for the learner.
- Surfaces corrections at the end of the session.
"""

import logging
from pathlib import Path
from typing import Any

from src.evaluation.calibration_maps import load_map
from src.llm import governance
from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.llm.schemas import GrammarAnalysis, GrammarErrorModel
from src.orchestrator.state import GrammarError, LearnerState

logger = logging.getLogger("polyglot.grammar")

#: Minimum confidence for a genuine error to be surfaced: the calibrated
#: probability when the answering model has a calibration map, else the raw
#: confidence. Below this the agent abstains rather than risk a false
#: correction.
_MIN_ERROR_CONFIDENCE = 0.5
#: Models already reported as uncalibrated (logged once per process).
_uncalibrated_logged: set[str] = set()


#: Generation parameters of the production grammar call (shared with the
#: real-model evaluation runner so it measures exactly what production sends).
GRAMMAR_TEMPERATURE = 0.0
GRAMMAR_MAX_TOKENS = 700
GRAMMAR_SYSTEM_MESSAGE = "You are a precise grammar analysis tool. Respond only in JSON."


def build_grammar_messages(
    language: str,
    *,
    cefr_level: str,
    weaknesses: list[str],
    user_text: str,
    prompt_name: str = "grammar",
    prompt_version: int | None = None,
    **extra: Any,
) -> list[Message]:
    """The exact messages the grammar agent sends for one learner text.

    ``prompt_name``/``prompt_version`` select a registered prompt variant
    (production uses the current ``grammar`` prompt); ``extra`` supplies any
    variables a variant needs (e.g. ``context``).
    """
    prompt = str(
        render_prompt(
            prompt_name,
            version=prompt_version,
            language=language,
            cefr_level=cefr_level,
            weaknesses=", ".join(weaknesses) or "none identified yet",
            user_text=user_text,
            **extra,
        )
    )
    return [Message("system", GRAMMAR_SYSTEM_MESSAGE), Message("user", prompt)]


async def grammar_node(state: LearnerState) -> dict[str, Any]:
    """Detect and classify grammar deviations in the user's latest input.

    Runs silently. Only genuine, confident errors are kept; acceptable variants
    (regional/informal/acceptable) and low-confidence flags are dropped.
    """
    user_input = state.get("last_user_input", "")

    if not user_input or len(user_input.strip()) < 3:
        return {"grammar_errors": []}

    messages = build_grammar_messages(
        state["language"],
        cefr_level=state.get("cefr_level", "A2"),
        weaknesses=state.get("grammar_weaknesses", []),
        user_text=user_input,
    )

    # Fast tier, deterministic, structured output validated against a schema.
    # Analysis is silent and best-effort: a total provider outage means no
    # findings this turn, not a crashed session.
    provider = get_provider("fast")
    try:
        analysis = await provider.generate_structured(
            messages,
            GrammarAnalysis,
            temperature=GRAMMAR_TEMPERATURE,
            max_tokens=GRAMMAR_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 - analysis must never break the turn
        logger.warning("Grammar analysis skipped, no LLM provider answered: %s", exc)
        return {"grammar_errors": state.get("grammar_errors", [])}

    errors = _select_errors(analysis, model_key=governance.last_answer())

    return {"grammar_errors": state.get("grammar_errors", []) + errors}


def _select_errors(
    analysis: GrammarAnalysis | None,
    *,
    model_key: str | None = None,
    calibration_dir: Path | None = None,
) -> list[GrammarError]:
    """Turn a validated analysis into the genuine, confident errors to surface.

    Filters out acceptable variation (regional/informal/acceptable/...) and
    low-confidence flags, then maps each surviving model into the backward
    -compatible :class:`GrammarError` dict (legacy keys preserved).

    ``model_key`` (``provider:model``) is the model that answered. With a
    fitted calibration map for it, the threshold applies to the calibrated
    probability, which also replaces ``confidence`` (the model's own value is
    kept as ``raw_confidence``). Without one, the raw confidence is used and
    the model is logged once as uncalibrated.
    """
    if analysis is None:
        return []

    calibration = load_map(model_key, calibration_dir) if model_key else None
    if calibration is None:
        label = model_key or "unknown model"
        if label not in _uncalibrated_logged:
            _uncalibrated_logged.add(label)
            logger.info("grammar confidence for %s is uncalibrated (no calibration map)", label)

    kept: list[GrammarError] = []
    for e in analysis.errors:
        if not e.original:
            continue
        if not e.is_error():
            continue  # acceptable variation — do not correct
        confidence = e.confidence if calibration is None else calibration(e.confidence)
        if confidence < _MIN_ERROR_CONFIDENCE:
            continue  # abstain rather than risk a false correction
        error = _to_grammar_error(e)
        if calibration is not None:
            error["raw_confidence"] = e.confidence
            error["confidence"] = round(confidence, 4)
        kept.append(error)
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
