"""Tests for the Cross-Language Transfer Agent."""

from __future__ import annotations

import pytest

from src.agents import transfer
from src.config import settings
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls.append({"json_mode": json_mode})
        return self.reply


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    return data_dir


_COGNATE_PAYLOAD = (
    '{"transfers": [{"word": "restaurante", '
    '"cognates": {"Italian": "ristorante", "Polish": "restauracja"}, '
    '"false_friends": []}]}'
)


class TestSuggestTransfers:
    async def test_returns_cognates(self, monkeypatch):
        monkeypatch.setattr(transfer, "get_provider", lambda tier: FakeProvider(_COGNATE_PAYLOAD))
        out = await transfer.suggest_transfers(
            "Spanish", ["restaurante"], ["Italian", "Polish"]
        )
        assert out[0]["word"] == "restaurante"
        assert out[0]["cognates"]["Italian"] == "ristorante"

    async def test_returns_false_friend(self, monkeypatch):
        payload = (
            '{"transfers": [{"word": "burro", "cognates": {}, '
            '"false_friends": [{"language": "Italian", "word": "burro", '
            '"warning": "burro means butter in Italian, donkey in Spanish"}]}]}'
        )
        monkeypatch.setattr(transfer, "get_provider", lambda tier: FakeProvider(payload))
        out = await transfer.suggest_transfers("Spanish", ["burro"], ["Italian"])
        assert out[0]["false_friends"][0]["language"] == "Italian"
        assert "butter" in out[0]["false_friends"][0]["warning"]

    async def test_uses_json_mode(self, monkeypatch):
        fake = FakeProvider('{"transfers": []}')
        monkeypatch.setattr(transfer, "get_provider", lambda tier: fake)
        await transfer.suggest_transfers("Spanish", ["x"], ["Italian"])
        assert fake.calls[0]["json_mode"] is True

    async def test_no_words_no_call(self, monkeypatch):
        def boom(tier):
            raise AssertionError("should not call provider with no words")

        monkeypatch.setattr(transfer, "get_provider", boom)
        assert await transfer.suggest_transfers("Spanish", [], ["Italian"]) == []

    async def test_no_other_languages_no_call(self, monkeypatch):
        def boom(tier):
            raise AssertionError("should not call provider with no other languages")

        monkeypatch.setattr(transfer, "get_provider", boom)
        assert await transfer.suggest_transfers("Spanish", ["mesa"], []) == []

    async def test_llm_failure_returns_empty(self, monkeypatch):
        class Boom(LLMProvider):
            name = "boom"

            def is_available(self):
                return True

            async def generate(self, *a, **k):
                raise RuntimeError("down")

        monkeypatch.setattr(transfer, "get_provider", lambda tier: Boom())
        assert await transfer.suggest_transfers("Spanish", ["mesa"], ["Italian"]) == []


class TestTransferNode:
    async def test_maps_new_vocabulary(self, temp_storage, monkeypatch):
        from src.memory import user_profile

        user_profile.create_profile(
            "u1", target_languages=["Spanish", "Italian", "Polish"]
        )
        monkeypatch.setattr(transfer, "get_provider", lambda tier: FakeProvider(_COGNATE_PAYLOAD))

        state = {
            "user_id": "u1",
            "language": "Spanish",
            "new_vocabulary": [{"word": "restaurante", "translation": "restaurant"}],
        }
        result = await transfer.transfer_node(state)
        assert result["transfer_suggestions"][0]["word"] == "restaurante"

    async def test_excludes_source_language(self, temp_storage, monkeypatch):
        from src.memory import user_profile

        user_profile.create_profile(
            "u1", target_languages=["Spanish", "Italian"]
        )
        captured = {}

        async def fake_suggest(source, words, others):
            captured["others"] = others
            return []

        monkeypatch.setattr(transfer, "suggest_transfers", fake_suggest)
        state = {
            "user_id": "u1",
            "language": "Spanish",
            "new_vocabulary": [{"word": "mesa"}],
        }
        await transfer.transfer_node(state)
        assert captured["others"] == ["Italian"]

    async def test_no_new_vocab_empty(self, temp_storage):
        state = {"user_id": "u1", "language": "Spanish", "new_vocabulary": []}
        result = await transfer.transfer_node(state)
        assert result["transfer_suggestions"] == []
