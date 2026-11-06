"""Analysis agents degrade to "no findings" on a total LLM outage.

The conversation node already falls back to a canned reply when every
provider fails, but the grammar, vocabulary and cultural nodes let
``NoProviderAvailableError`` escape. Since the CLI and Gradio app now wait for
analysis (via ``src.api.sessions.run_turn``), that crashed the whole session
on the first turn whenever no backend answered (e.g. every API key invalid).
"""

from __future__ import annotations

import pytest

from src.agents import cultural, grammar, vocabulary
from src.llm.factory import NoProviderAvailableError
from src.llm.provider import LLMProvider


class AlwaysFailsProvider(LLMProvider):
    name = "always-fails"

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        raise NoProviderAvailableError("All providers failed for tier='fast'")


def _state(**overrides):
    state = {
        "session_id": "s1",
        "user_id": "u1",
        "language": "Spanish",
        "cefr_level": "A2",
        "current_scenario": {"persona": {"name": "Ana", "role": "waiter"}},
        "last_user_input": "Hola, yo soy hambre",
        "agent_response": "Disculpa, no te escuché bien.",
        "grammar_errors": [],
        "new_vocabulary": [],
        "cultural_notes": [],
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    ("module", "node", "key"),
    [
        (grammar, "grammar_node", "grammar_errors"),
        (vocabulary, "vocabulary_node", "new_vocabulary"),
        (cultural, "cultural_node", "cultural_notes"),
    ],
)
async def test_total_outage_yields_no_findings_instead_of_raising(monkeypatch, module, node, key):
    monkeypatch.setattr(module, "get_provider", lambda tier: AlwaysFailsProvider())

    result = await getattr(module, node)(_state())

    assert result == {key: []}


async def test_outage_keeps_findings_from_earlier_turns(monkeypatch):
    monkeypatch.setattr(vocabulary, "get_provider", lambda tier: AlwaysFailsProvider())
    earlier = [{"word": "mesa", "translation": "table", "pos": "noun", "is_new": True}]

    result = await vocabulary.vocabulary_node(_state(new_vocabulary=earlier))

    assert result == {"new_vocabulary": earlier}
