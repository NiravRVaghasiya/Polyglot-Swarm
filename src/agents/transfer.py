"""Cross-Language Transfer Agent — exploits similarities across the learner's
target languages.

For words the learner just encountered, it suggests cognates in their OTHER
active languages (e.g. ES "restaurante" -> IT "ristorante" -> PL "restauracja")
and warns about false friends. This turns prior knowledge into leverage,
especially between closely related languages (ES/IT ~82% lexical similarity).

Runs at end of session (surfaced in the report), not during conversation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.languages.transfer_graph import candidates_for_words
from src.llm.factory import get_provider
from src.llm.prompts import render_prompt
from src.llm.provider import Message
from src.llm.schemas import TransferEdge
from src.memory import user_profile
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.transfer")


def _candidates_to_suggestions(candidates: list[TransferEdge]) -> list[dict[str, Any]]:
    """Assemble resource candidates into the transfer_suggestions shape.

    Used as the offline/degraded fallback: resource-backed relations are already
    trustworthy, so we can surface them without LLM verification if the model is
    unavailable. Groups by source word; cognates -> {lang: word}, false friends
    -> [{language, word, warning}].
    """
    by_word: dict[str, dict[str, Any]] = {}
    for edge in candidates:
        entry = by_word.setdefault(
            edge.source_word, {"word": edge.source_word, "cognates": {}, "false_friends": []}
        )
        if edge.relation == "cognate" and edge.target_word:
            entry["cognates"][edge.target_language] = edge.target_word
        elif edge.relation == "false_friend":
            entry["false_friends"].append(
                {
                    "language": edge.target_language,
                    "word": edge.target_word,
                    "warning": edge.note,
                }
            )
    # Keep only words that actually have a cognate or false friend.
    return [e for e in by_word.values() if e["cognates"] or e["false_friends"]]


async def suggest_transfers(
    source_language: str,
    words: list[str],
    other_languages: list[str],
) -> list[dict[str, Any]]:
    """Return cognate/false-friend transfer suggestions for ``words``.

    Phase 11: candidates are RETRIEVED from the language-pack transfer resources
    (a linguistic resource, not embedding similarity or pure invention); an LLM
    then VERIFIES them. When a resource has candidates, the verify prompt is
    used and the LLM output is preferred, falling back to the resource
    candidates if the LLM is unavailable. When there is no resource, the agent
    degrades to an open-ended prompt so unknown language pairs still work.

    Args:
        source_language: The language the words are in.
        words: Words to analyze (typically newly learned this session).
        other_languages: The learner's other active languages to map to.

    Returns:
        A list of transfer entries; empty if there is nothing to map.
    """
    if not words or not other_languages:
        return []

    candidates = candidates_for_words(source_language, words, other_languages)

    if candidates:
        prompt = str(
            render_prompt(
                "transfer_verify",
                source_language=source_language,
                other_languages=other_languages,
                candidates=candidates,
            )
        )
    else:
        prompt = str(
            render_prompt(
                "transfer",
                source_language=source_language,
                other_languages=other_languages,
                words=words,
            )
        )

    provider = get_provider("fast")
    try:
        response_text = await provider.generate(
            [
                Message("system", "You are a cross-language transfer coach. Respond only in JSON."),
                Message("user", prompt),
            ],
            temperature=0.2,
            max_tokens=700,
            json_mode=True,
        )
    except Exception as exc:  # noqa: BLE001 - transfer is a best-effort extra
        logger.warning("Transfer LLM call failed: %s", exc)
        # Resource-backed candidates are trustworthy on their own.
        return _candidates_to_suggestions(candidates)

    verified = _parse_transfers(response_text)
    # If the model returned nothing usable but we had resource candidates, still
    # surface them (verified-by-resource) rather than dropping real relations.
    if not verified and candidates:
        return _candidates_to_suggestions(candidates)
    return verified


def _parse_transfers(response_text: str) -> list[dict[str, Any]]:
    """Parse the transfer LLM JSON response, tolerating code fences."""
    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        transfers = data.get("transfers", [])
        result: list[dict[str, Any]] = []
        for t in transfers:
            word = t.get("word")
            if not word:
                continue
            result.append(
                {
                    "word": word,
                    "cognates": t.get("cognates", {}) or {},
                    "false_friends": t.get("false_friends", []) or [],
                }
            )
        return result
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return []


async def transfer_node(state: LearnerState) -> dict[str, Any]:
    """Generate transfer suggestions for the session's new vocabulary.

    Reads the learner's other active languages from their profile, asks for
    cognates/false friends for the new words, and returns them on state under
    ``transfer_suggestions`` for the end-of-session report.
    """
    new_vocab = state.get("new_vocabulary", [])
    words = [v["word"] for v in new_vocab if v.get("word")]
    if not words:
        return {"transfer_suggestions": []}

    source_language = state["language"]
    profile = user_profile.load_profile(state["user_id"])
    other_languages = [lang for lang in profile.target_languages if lang != source_language]

    suggestions = await suggest_transfers(source_language, words, other_languages)
    return {"transfer_suggestions": suggestions}
