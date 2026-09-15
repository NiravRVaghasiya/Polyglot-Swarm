"""Shared pack-path resolution for language packs.

Language packs live under the repository's top-level ``languages/<code>/``
directory. Both the grammar taxonomy loader (Phase 4) and the general pack
loader (Phase 10) resolve a full language name (or code) to that directory the
same way — this module holds that single mapping so they never drift.
"""

from __future__ import annotations

from pathlib import Path

# Full language name -> pack directory code (es/pl/it). Keyed the other way from
# the orchestrator's _LANG_CODE_TO_NAME. The app uses full names everywhere;
# codes appear only in pack directories and scenario files.
NAME_TO_CODE: dict[str, str] = {
    "spanish": "es",
    "polish": "pl",
    "italian": "it",
}

# Repo root: this file is src/languages/paths.py -> parents[2].
REPO_ROOT = Path(__file__).resolve().parents[2]


def pack_code(language: str) -> str | None:
    """Map a full language name (or a raw code) to a pack directory code.

    Returns ``None`` for a language with no pack, so loaders can degrade to
    empty (the app still works generically for unknown languages).
    """
    key = language.strip().lower()
    if key in NAME_TO_CODE:
        return NAME_TO_CODE[key]
    if key in NAME_TO_CODE.values():
        return key
    return None


def pack_dir(language: str) -> Path | None:
    """Return the pack directory for a language, or ``None`` if unknown."""
    code = pack_code(language)
    if code is None:
        return None
    return REPO_ROOT / "languages" / code
