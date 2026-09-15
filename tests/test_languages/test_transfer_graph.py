"""Phase 11 tests: the cross-language transfer graph (resource-backed candidate
retrieval) and the resource-verify path in the transfer agent."""

from __future__ import annotations

import pytest

from src.agents import transfer
from src.agents.transfer import _candidates_to_suggestions, suggest_transfers
from src.languages import transfer_graph
from src.llm.provider import LLMProvider
from src.llm.schemas import TransferEdge


class _FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


class TestTransferGraph:
    def test_cognate_candidate_retrieved(self):
        edges = transfer_graph.candidates_for_word("Spanish", "restaurante", "Italian")
        assert edges
        assert edges[0].relation == "cognate"
        assert edges[0].target_word == "ristorante"

    def test_false_friend_candidate(self):
        edges = transfer_graph.candidates_for_word("Spanish", "burro", "Italian")
        assert any(e.relation == "false_friend" for e in edges)

    def test_interference_candidate_es_pl(self):
        edges = transfer_graph.candidates_for_word("Spanish", "mesa", "Polish")
        assert any(e.relation == "interference" for e in edges)

    def test_case_insensitive_match(self):
        assert transfer_graph.candidates_for_word("Spanish", "FAMILIA", "Italian")

    def test_no_resource_returns_empty(self):
        assert transfer_graph.candidates_for_word("Spanish", "mesa", "Klingon") == []

    def test_candidates_for_words_across_languages(self):
        edges = transfer_graph.candidates_for_words(
            "Spanish", ["restaurante"], ["Italian", "Polish"]
        )
        langs = {e.target_language for e in edges}
        assert "Italian" in langs and "Polish" in langs

    def test_has_transfer_resource(self):
        assert transfer_graph.has_transfer_resource("Spanish", "Italian")
        assert not transfer_graph.has_transfer_resource("Spanish", "Klingon")

    def test_transfer_edge_is_positive(self):
        assert TransferEdge(source_word="x", target_language="It", relation="cognate").is_positive()
        assert not TransferEdge(
            source_word="x", target_language="It", relation="false_friend"
        ).is_positive()


class TestCandidatesToSuggestions:
    def test_groups_cognates_and_false_friends(self):
        edges = [
            TransferEdge(
                source_word="familia",
                target_language="Italian",
                target_word="famiglia",
                relation="cognate",
            ),
            TransferEdge(
                source_word="burro",
                target_language="Italian",
                target_word="burro",
                relation="false_friend",
                note="donkey vs butter",
            ),
        ]
        out = _candidates_to_suggestions(edges)
        by_word = {e["word"]: e for e in out}
        assert by_word["familia"]["cognates"] == {"Italian": "famiglia"}
        assert by_word["burro"]["false_friends"][0]["warning"] == "donkey vs butter"

    def test_interference_only_dropped(self):
        # An interference edge (no target word) has neither cognate nor false
        # friend, so it produces no suggestion entry.
        edges = [
            TransferEdge(
                source_word="mesa",
                target_language="Polish",
                relation="interference",
                note="case ending",
            )
        ]
        assert _candidates_to_suggestions(edges) == []


class TestVerifyPath:
    async def test_resource_fallback_when_llm_unusable(self, monkeypatch):
        # Fake returns non-matching JSON -> _parse_transfers yields [] -> the
        # resource-backed candidates are surfaced (verified-by-resource).
        monkeypatch.setattr(transfer, "get_provider", lambda tier: _FakeProvider('{"x": 1}'))
        out = await suggest_transfers("Spanish", ["restaurante", "burro"], ["Italian"])
        words = {e["word"] for e in out}
        assert "restaurante" in words
        assert "burro" in words

    async def test_llm_verification_preferred_when_present(self, monkeypatch):
        payload = (
            '{"transfers": [{"word": "restaurante", '
            '"cognates": {"Italian": "ristorante"}, "false_friends": []}]}'
        )
        monkeypatch.setattr(transfer, "get_provider", lambda tier: _FakeProvider(payload))
        out = await suggest_transfers("Spanish", ["restaurante"], ["Italian"])
        assert out[0]["cognates"]["Italian"] == "ristorante"

    async def test_no_resource_falls_back_to_open_prompt(self, monkeypatch):
        # No es->Klingon resource; open prompt used, fake returns nothing usable.
        monkeypatch.setattr(transfer, "get_provider", lambda tier: _FakeProvider('{"x":1}'))
        out = await suggest_transfers("Spanish", ["mesa"], ["Klingon"])
        assert out == []

    async def test_llm_failure_falls_back_to_resource(self, monkeypatch):
        class Boom(_FakeProvider):
            async def generate(self, *a, **k):
                raise RuntimeError("down")

        monkeypatch.setattr(transfer, "get_provider", lambda tier: Boom(""))
        out = await suggest_transfers("Spanish", ["restaurante"], ["Italian"])
        assert any(e["word"] == "restaurante" for e in out)


@pytest.fixture(autouse=True)
def _clear_transfer_cache():
    """Transfer-graph loads are cached; clear between tests for isolation."""
    transfer_graph._load_transfer_file.cache_clear()
    yield
    transfer_graph._load_transfer_file.cache_clear()
