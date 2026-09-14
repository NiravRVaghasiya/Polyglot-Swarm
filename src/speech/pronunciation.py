"""Pronunciation feedback — compare an STT transcript against the target text.

When a learner speaks, Whisper transcribes what it *heard*. Comparing that
transcript to the sentence the learner was *meant* to say surfaces likely
pronunciation problems: words the ASR misheard are words that were probably
mispronounced. This module does a deterministic token-level comparison (no
external deps) and produces per-word feedback plus an overall accuracy score
that the session report can surface.

This is a heuristic, not a phonetic analyzer: it aligns words and scores each
by character-level similarity, so near-misses (accent/ending errors) score
higher than words the ASR completely failed to recognize.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# A per-word similarity at or above this is treated as correctly pronounced.
_WORD_OK_THRESHOLD = 0.8


def _normalize(text: str) -> list[str]:
    """Lowercase word tokens, punctuation stripped, accents preserved."""
    return re.findall(r"\w+", text.lower(), flags=re.UNICODE)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def assess_pronunciation(target: str, transcript: str) -> dict[str, Any]:
    """Compare a spoken ``transcript`` against the ``target`` sentence.

    Returns a dict with:
    - ``accuracy``: overall fraction of target words pronounced well (0.0–1.0).
    - ``words``: per-target-word ``{target, heard, similarity, ok}``.
    - ``problem_words``: the target words that scored below the threshold.
    """
    target_words = _normalize(target)
    heard_words = _normalize(transcript)

    if not target_words:
        return {"accuracy": 0.0, "words": [], "problem_words": []}

    matcher = SequenceMatcher(None, target_words, heard_words)
    per_word: list[dict[str, Any]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                word = target_words[i1 + offset]
                per_word.append(
                    {"target": word, "heard": word, "similarity": 1.0, "ok": True}
                )
        elif tag == "replace":
            # Align replaced spans positionally; score by char similarity.
            for offset in range(i2 - i1):
                t = target_words[i1 + offset]
                heard = heard_words[j1 + offset] if j1 + offset < j2 else ""
                sim = _similarity(t, heard) if heard else 0.0
                per_word.append(
                    {
                        "target": t,
                        "heard": heard,
                        "similarity": sim,
                        "ok": sim >= _WORD_OK_THRESHOLD,
                    }
                )
        elif tag == "delete":
            # Target words the ASR did not hear at all.
            for offset in range(i2 - i1):
                t = target_words[i1 + offset]
                per_word.append({"target": t, "heard": "", "similarity": 0.0, "ok": False})
        # "insert" = extra heard words with no target counterpart; ignored for
        # per-target scoring (they don't map to a target word).

    ok_count = sum(1 for w in per_word if w["ok"])
    accuracy = ok_count / len(target_words)
    problem_words = [w["target"] for w in per_word if not w["ok"]]

    return {
        "accuracy": round(accuracy, 3),
        "words": per_word,
        "problem_words": problem_words,
    }


def feedback_note(target: str, transcript: str) -> str | None:
    """Return a short human-readable pronunciation note, or None if perfect.

    Suitable for appending to the end-of-session report.
    """
    result = assess_pronunciation(target, transcript)
    if not result["words"]:
        return None
    if not result["problem_words"]:
        return f"🎤 Pronunciation: excellent ({int(result['accuracy'] * 100)}% clear)."
    words = ", ".join(result["problem_words"][:5])
    return (
        f"🎤 Pronunciation: {int(result['accuracy'] * 100)}% clear. "
        f"Practice these words: {words}."
    )
