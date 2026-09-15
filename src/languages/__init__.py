"""Language packs — explicit, language-specific linguistic knowledge.

The plan (Phase 10) replaces the "any language with zero configuration" claim
with a defensible architecture where generic agent infrastructure stays
reusable but language-specific knowledge (grammar constructions, later:
frequency, collocations, register, transfer) is explicit and version-controlled
under the top-level ``languages/`` directory.

Phase 4 seeds the grammar taxonomy for the three validation languages
(Spanish, Polish, Italian) and provides the loader here. The full pack layout
(``metadata.yaml``, ``grammar/``, ``frequency/``, ``collocations/`` ...) is
introduced incrementally by later phases.
"""

from src.languages.grammar_taxonomy import (
    get_construction,
    list_constructions,
    load_taxonomy,
)
from src.languages.pack import (
    collocations_for,
    frequency_rank,
    has_pack,
    load_pack,
    register_notes_for,
)

__all__ = [
    "collocations_for",
    "frequency_rank",
    "get_construction",
    "has_pack",
    "list_constructions",
    "load_pack",
    "load_taxonomy",
    "register_notes_for",
]
