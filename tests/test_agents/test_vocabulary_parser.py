"""The vocabulary parser tolerates off-contract JSON instead of crashing.

Found by the real-model benchmark: a local model answered with a bare JSON
list, and ``_parse_vocabulary_response`` raised ``AttributeError`` (only
decode, key and type errors were caught), which would break the turn.
"""

from __future__ import annotations

import pytest

from src.agents.vocabulary import _parse_vocabulary_response


@pytest.mark.parametrize(
    "text",
    [
        '[{"word": "mesa", "translation": "table"}]',
        '"mesa"',
        "42",
        '{"words": {"word": "mesa"}}',
        '{"words": ["mesa", 3, null]}',
    ],
)
def test_off_contract_json_yields_no_words(text):
    assert _parse_vocabulary_response(text) == []


def test_valid_items_survive_alongside_invalid_ones():
    items = _parse_vocabulary_response(
        '{"words": ["junk", {"word": "mesa", "translation": "table"}, {"word": ""}]}'
    )
    assert [i["word"] for i in items] == ["mesa"]
    assert items[0]["translation"] == "table"
