"""Conflict reconciliation between agents.

Agents can disagree: the Grammar agent flags a form the Cultural agent considers
perfectly fine in this register (e.g. an informal contraction among friends).
The plan wants these reconciled via pedagogical notes rather than blunt drops.
This module provides a small, deterministic reconciliation used by the verifier
before/alongside the LLM pass.
"""

from __future__ import annotations

from typing import Any

# Cues in a cultural note that signal "informal/casual is acceptable here".
_INFORMAL_CUES = ("informal", "casual", "colloquial", "friends", "slang")


def _note_mentions(notes: list[str], word: str) -> bool:
    low = word.lower()
    return any(low in note.lower() for note in notes)


def reconcile_grammar_culture(
    grammar_errors: list[dict[str, Any]],
    cultural_notes: list[str],
) -> list[dict[str, Any]]:
    """Return indices/reasons where a grammar error conflicts with a cultural note.

    A conflict is flagged when a grammar error's classification is already a
    register/formality matter (informal/regional/formal) AND a cultural note
    endorses that register. The caller (verifier) decides how to act — typically
    abstain or reject the "correction" and keep a pedagogical note.

    Returns a list of ``{"index", "reason"}`` conflict records.
    """
    conflicts: list[dict[str, Any]] = []
    endorses_informal = any(
        any(cue in note.lower() for cue in _INFORMAL_CUES) for note in cultural_notes
    )
    for i, err in enumerate(grammar_errors):
        classification = (err.get("classification") or "wrong").lower()
        original = err.get("original", "")
        register_matter = classification in ("informal", "regional", "formal")
        if register_matter and (endorses_informal or _note_mentions(cultural_notes, original)):
            conflicts.append(
                {
                    "index": i,
                    "reason": (
                        f"'{original}' is a {classification} form the cultural context accepts; "
                        "not correcting it."
                    ),
                }
            )
    return conflicts
