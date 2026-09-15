"""Hand-labeled vocabulary-extraction dataset: raw responses + expected words.

Each case is a raw model response text (exactly the shape
:func:`src.agents.vocabulary._parse_vocabulary_response` receives — plain JSON,
markdown-fenced JSON, or malformed/empty text) paired with the set of words a
correct extraction should recover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bump when cases are added/changed/removed.
DATASET_VERSION = "2026.09.0"


@dataclass(frozen=True)
class VocabExtractionCase:
    """One (raw model response, expected extracted words) pair."""

    name: str
    raw_response: str
    expected_words: frozenset[str] = field(default_factory=frozenset)


CASES: list[VocabExtractionCase] = [
    VocabExtractionCase(
        name="single_word",
        raw_response=(
            '{"words": [{"word": "mesa", "translation": "table", "pos": "noun", '
            '"context_sentence": "Quiero una mesa para dos."}]}'
        ),
        expected_words=frozenset({"mesa"}),
    ),
    VocabExtractionCase(
        name="multiple_words",
        raw_response=(
            '{"words": ['
            '{"word": "reserva", "translation": "reservation", "pos": "noun"},'
            '{"word": "propina", "translation": "tip", "pos": "noun"}'
            "]}"
        ),
        expected_words=frozenset({"reserva", "propina"}),
    ),
    VocabExtractionCase(
        name="markdown_fenced_json",
        raw_response=('```json\n{"words": [{"word": "madrugar", "pos": "verb"}]}\n```'),
        expected_words=frozenset({"madrugar"}),
    ),
    VocabExtractionCase(
        name="no_new_vocabulary",
        raw_response='{"words": []}',
        expected_words=frozenset(),
    ),
    VocabExtractionCase(
        name="word_missing_key_is_skipped",
        # An item with no "word" key must be dropped, not crash the parser.
        raw_response=('{"words": [{"translation": "no word key"}, {"word": "biblioteca"}]}'),
        expected_words=frozenset({"biblioteca"}),
    ),
    VocabExtractionCase(
        name="malformed_json_yields_empty",
        raw_response="not valid json at all",
        expected_words=frozenset(),
    ),
    VocabExtractionCase(
        name="empty_string_yields_empty",
        raw_response="",
        expected_words=frozenset(),
    ),
]
