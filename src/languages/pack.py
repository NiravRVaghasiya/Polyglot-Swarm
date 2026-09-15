"""General language-pack loader (Phase 10).

Assembles a :class:`~src.llm.schemas.LanguagePack` from the files under
``languages/<code>/``:

    metadata.yaml            top-level metadata (family, dialect, writing system)
    grammar/constructions.yaml   the grammar taxonomy (loaded by grammar_taxonomy)
    frequency/frequency.txt      one word per line, most-frequent first
    collocations/collocations.yaml  fixed multi-word units
    register/register.yaml       register/formality notes

Every resource is optional — a missing file yields an empty section, so a
partial pack still loads and the app degrades gracefully for languages without
a pack. Loads are cached per language.

This replaces the "any language with zero configuration" claim with a
defensible architecture: reusable generic agents plus explicit, versioned
language knowledge.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from src.languages.grammar_taxonomy import list_constructions
from src.languages.paths import pack_code, pack_dir
from src.llm.schemas import (
    CollocationItem,
    GrammarItem,
    LanguageMetadata,
    LanguagePack,
    RegisterNote,
)


def _load_metadata(directory: Path, language: str, code: str) -> LanguageMetadata:
    path = directory / "metadata.yaml"
    if not path.exists():
        return LanguageMetadata(language=language, code=code)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return LanguageMetadata(
        language=raw.get("language", language),
        code=raw.get("code", code),
        family=raw.get("family", ""),
        dialect=raw.get("dialect", ""),
        writing_system=raw.get("writing_system", "Latin"),
        notes=raw.get("notes", ""),
    )


def _load_frequency(directory: Path) -> list[str]:
    path = directory / "frequency" / "frequency.txt"
    if not path.exists():
        return []
    words: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.append(word)
    return words


def _load_collocations(directory: Path) -> list[CollocationItem]:
    path = directory / "collocations" / "collocations.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items: list[CollocationItem] = []
    for entry in raw.get("collocations", []):
        try:
            items.append(
                CollocationItem(
                    phrase=entry["phrase"],
                    translation=entry.get("translation", ""),
                    pattern=entry.get("pattern", ""),
                    cefr=entry.get("cefr", "A1"),
                    register=entry.get("register", "neutral"),  # alias -> register_label
                )
            )
        except (KeyError, TypeError):
            continue
    return items


def _load_register(directory: Path) -> list[RegisterNote]:
    path = directory / "register" / "register.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    notes: list[RegisterNote] = []
    for entry in raw.get("notes", []):
        try:
            notes.append(
                RegisterNote(
                    topic=entry["topic"],
                    note=entry.get("note", ""),
                    register=entry.get("register", "neutral"),  # alias -> register_label
                )
            )
        except (KeyError, TypeError):
            continue
    return notes


@functools.cache
def load_pack(language: str) -> LanguagePack | None:
    """Load the full language pack for ``language``, or ``None`` if none exists.

    Cached per language. A pack with only some resource files still loads (the
    rest are empty).
    """
    code = pack_code(language)
    directory = pack_dir(language)
    if code is None or directory is None or not directory.exists():
        return None
    return LanguagePack(
        metadata=_load_metadata(directory, language, code),
        frequency=_load_frequency(directory),
        collocations=_load_collocations(directory),
        register_notes=_load_register(directory),
    )


def has_pack(language: str) -> bool:
    """Whether a language pack directory exists for ``language``."""
    directory = pack_dir(language)
    return directory is not None and directory.exists()


def frequency_rank(language: str, word: str) -> int | None:
    """Return the 1-based frequency rank of a word (lower = commoner), or None."""
    pack = load_pack(language)
    if pack is None:
        return None
    lower = word.strip().lower()
    for i, w in enumerate(pack.frequency):
        if w.lower() == lower:
            return i + 1
    return None


def collocations_for(language: str) -> list[CollocationItem]:
    """Return the language's collocations (may be empty)."""
    pack = load_pack(language)
    return pack.collocations if pack else []


def register_notes_for(language: str) -> list[RegisterNote]:
    """Return the language's register notes (may be empty)."""
    pack = load_pack(language)
    return pack.register_notes if pack else []


def grammar_constructions(language: str) -> list[GrammarItem]:
    """Return the language's grammar constructions (from the taxonomy loader)."""
    return list_constructions(language)
