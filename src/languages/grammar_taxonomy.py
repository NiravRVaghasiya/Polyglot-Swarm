"""Loader for the language-pack grammar taxonomy.

Reads the per-language ``languages/<code>/grammar/constructions.yaml`` packs and
exposes them as validated :class:`~src.llm.schemas.GrammarItem` objects. The
grammar agent and (later) the curriculum planner use this to ground
construction ids, CEFR levels, prerequisites, and known interferences — so the
taxonomy is explicit data, not buried in a prompt.

Language is addressed by the full name the app uses everywhere ("Spanish",
"Polish", "Italian"); the loader maps it to the pack directory code. Unknown
languages return an empty taxonomy (the agent still works generically).
"""

from __future__ import annotations

import functools

import yaml

from src.languages.paths import REPO_ROOT, pack_code
from src.llm.schemas import GrammarItem


@functools.cache
def load_taxonomy(language: str) -> dict[str, GrammarItem]:
    """Load a language's grammar taxonomy, keyed by construction id.

    Returns an empty dict for languages without a pack. Cached per language.
    """
    code = pack_code(language)
    if code is None:
        return {}
    path = REPO_ROOT / "languages" / code / "grammar" / "constructions.yaml"
    if not path.exists():
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lang_name = raw.get("language", language)
    items: dict[str, GrammarItem] = {}
    for entry in raw.get("constructions", []):
        try:
            item = GrammarItem(
                language=lang_name,
                construction=entry["construction"],
                cefr=entry.get("cefr", "A1"),
                explanation=(entry.get("explanation") or "").strip(),
                examples=list(entry.get("examples", [])),
                prerequisites=list(entry.get("prerequisites", [])),
                common_interferences=list(entry.get("common_interferences", [])),
            )
        except (KeyError, TypeError):
            continue
        items[item.construction] = item
    return items


def list_constructions(language: str) -> list[GrammarItem]:
    """Return all grammar constructions for a language (may be empty)."""
    return list(load_taxonomy(language).values())


def get_construction(language: str, construction: str) -> GrammarItem | None:
    """Return one construction by id, or ``None`` if not in the pack."""
    return load_taxonomy(language).get(construction)
