"""Writing exercises with detailed feedback.

A writing mode: the learner submits a paragraph and gets structured corrective
feedback — grammar/spelling corrections with rule references, style/register
notes, an encouraging overall assessment, and a clean corrected version.

Errors detected here also feed the persistent grammar error taxonomy (via
:mod:`src.memory.analytics`) so writing weaknesses inform future sessions, just
like conversation errors do.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.llm.factory import get_provider
from src.llm.prompts import render
from src.llm.provider import Message

logger = logging.getLogger("polyglot.writing")


async def assess_writing(
    language: str,
    text: str,
    *,
    cefr_level: str = "A2",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return structured writing feedback for ``text``.

    Result shape: ``{"corrections": [{original, correction, rule, explanation}],
    "style_notes": [...], "overall": str, "corrected_text": str}``.

    If ``user_id`` is given, each correction's rule is recorded in the learner's
    grammar error taxonomy so writing errors carry across sessions.
    """
    if not text.strip():
        return {"corrections": [], "style_notes": [], "overall": "", "corrected_text": ""}

    prompt = render("writing.jinja2", language=language, cefr_level=cefr_level, text=text)

    provider = get_provider("primary")
    try:
        response_text = await provider.generate(
            [
                Message("system", "You are a precise writing tutor. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.2,
            max_tokens=1200,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort feature
        logger.warning("Writing assessment LLM call failed: %s", exc)
        return {"corrections": [], "style_notes": [], "overall": "", "corrected_text": ""}

    result = _parse_writing(response_text)

    if user_id:
        _record_errors(user_id, language, result["corrections"])

    return result


def _parse_writing(response_text: str) -> dict[str, Any]:
    """Parse the writing-feedback JSON, tolerating code fences."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        corrections = [
            {
                "original": c.get("original", ""),
                "correction": c.get("correction", ""),
                "rule": c.get("rule", "unknown"),
                "explanation": c.get("explanation", ""),
            }
            for c in data.get("corrections", [])
            if c.get("original")
        ]
        return {
            "corrections": corrections,
            "style_notes": [s for s in data.get("style_notes", []) if isinstance(s, str)],
            "overall": data.get("overall", ""),
            "corrected_text": data.get("corrected_text", ""),
        }
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return {"corrections": [], "style_notes": [], "overall": "", "corrected_text": ""}


def _record_errors(user_id: str, language: str, corrections: list[dict[str, Any]]) -> None:
    """Persist correction rules into the grammar error taxonomy (best-effort)."""
    try:
        from src.memory import analytics

        for c in corrections:
            rule = c.get("rule") or "unknown"
            analytics.record_error(user_id, language, rule)
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        logger.warning("Failed to record writing errors: %s", exc)


def format_writing_feedback(result: dict[str, Any]) -> str:
    """Render writing feedback for display."""
    corrections = result.get("corrections", [])
    lines = ["✍️ Writing feedback", ""]
    if corrections:
        lines.append(f"Corrections ({len(corrections)}):")
        for c in corrections:
            lines.append(f"   • {c['original']} → {c['correction']}  [{c['rule']}]")
            if c.get("explanation"):
                lines.append(f"     {c['explanation']}")
    else:
        lines.append("No corrections — nicely done!")

    for note in result.get("style_notes", []):
        lines.append(f"✨ {note}")
    if result.get("overall"):
        lines += ["", result["overall"]]
    return "\n".join(lines)
