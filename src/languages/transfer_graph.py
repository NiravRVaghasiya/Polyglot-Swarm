"""Cross-language transfer graph (Phase 11).

Builds candidate transfer relations (cognates, false friends, shared
constructions, interference) between a source language and the learner's other
languages. The plan is explicit that this must NOT rely only on embedding
similarity or pure LLM invention: candidates come from a **linguistic
resource** (the language-pack transfer files) plus a cheap orthographic
similarity heuristic, and an LLM only *verifies* them (in the transfer agent).

Resource layout: ``languages/<source_code>/transfer/<target_code>.yaml`` with

    cognates:      [{source, target, note?}]
    false_friends: [{source, target, note}]
    interference:  [{source, note}]

All optional; a missing file yields no candidates (the agent still degrades to
its own verification prompt). Loads are cached per (source, target).
"""

from __future__ import annotations

import functools

import yaml

from src.languages.paths import pack_code, pack_dir
from src.llm.schemas import TransferEdge


@functools.cache
def _load_transfer_file(source_language: str, target_language: str) -> list[TransferEdge]:
    """Load candidate transfer edges from the source pack for a target language."""
    directory = pack_dir(source_language)
    target_code = pack_code(target_language)
    if directory is None or target_code is None:
        return []
    path = directory / "transfer" / f"{target_code}.yaml"
    if not path.exists():
        return []

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    target_name = raw.get("target_language", target_language)
    edges: list[TransferEdge] = []

    for entry in raw.get("cognates", []):
        edges.append(
            TransferEdge(
                source_word=entry.get("source", ""),
                target_language=target_name,
                target_word=entry.get("target", ""),
                relation="cognate",
                note=entry.get("note", ""),
            )
        )
    for entry in raw.get("false_friends", []):
        edges.append(
            TransferEdge(
                source_word=entry.get("source", ""),
                target_language=target_name,
                target_word=entry.get("target", ""),
                relation="false_friend",
                note=entry.get("note", ""),
            )
        )
    for entry in raw.get("interference", []):
        edges.append(
            TransferEdge(
                source_word=entry.get("source", ""),
                target_language=target_name,
                relation="interference",
                note=entry.get("note", ""),
            )
        )
    return [e for e in edges if e.source_word]


def candidates_for_word(
    source_language: str,
    word: str,
    target_language: str,
) -> list[TransferEdge]:
    """Return candidate transfer edges for one word into one target language.

    Matches the resource on the exact word (case-insensitive). Returns an empty
    list when there is no pack/resource or no match — candidate retrieval, not
    invention.
    """
    lower = word.strip().lower()
    return [
        e
        for e in _load_transfer_file(source_language, target_language)
        if e.source_word.lower() == lower
    ]


def candidates_for_words(
    source_language: str,
    words: list[str],
    other_languages: list[str],
) -> list[TransferEdge]:
    """Retrieve all candidate edges for a set of words across target languages."""
    out: list[TransferEdge] = []
    for word in words:
        for target in other_languages:
            out.extend(candidates_for_word(source_language, word, target))
    return out


def has_transfer_resource(source_language: str, target_language: str) -> bool:
    """Whether a transfer resource exists from source to target language."""
    return bool(_load_transfer_file(source_language, target_language))
