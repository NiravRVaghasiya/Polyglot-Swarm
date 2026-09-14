"""Tests for peer conversation mode (two-agent dialogue)."""

from __future__ import annotations

from src.agents import peer
from src.llm.provider import LLMProvider


class FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.last_prompt = ""

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.last_prompt = messages[-1].content
        return self.reply


_DIALOGUE = (
    '{"dialogue": ['
    '{"speaker": "Ana", "text": "¿Vamos al mercado?"},'
    '{"speaker": "Marco", "text": "Sí, necesito fruta."},'
    '{"speaker": "Ana", "text": "Yo compro pan."},'
    '{"speaker": "Marco", "text": "Perfecto, vamos."}'
    '], "comprehension": {"question": "Where are they going?", "answer": "the market"}}'
)


class TestGeneratePeerDialogue:
    async def test_two_speakers_alternate(self, monkeypatch):
        monkeypatch.setattr(peer, "get_provider", lambda tier: FakeProvider(_DIALOGUE))
        result = await peer.generate_peer_dialogue("Spanish", cefr_level="A2")

        speakers = [t["speaker"] for t in result["dialogue"]]
        assert speakers == ["Ana", "Marco", "Ana", "Marco"]

    async def test_includes_comprehension(self, monkeypatch):
        monkeypatch.setattr(peer, "get_provider", lambda tier: FakeProvider(_DIALOGUE))
        result = await peer.generate_peer_dialogue("Spanish")
        assert result["comprehension"]["question"] == "Where are they going?"
        assert result["comprehension"]["answer"] == "the market"

    async def test_prompt_carries_speakers_and_topic(self, monkeypatch):
        fake = FakeProvider(_DIALOGUE)
        monkeypatch.setattr(peer, "get_provider", lambda tier: fake)
        await peer.generate_peer_dialogue(
            "Spanish", topic="at the market", speaker_a="Ana", speaker_b="Marco"
        )
        assert "at the market" in fake.last_prompt
        assert "Ana" in fake.last_prompt and "Marco" in fake.last_prompt

    async def test_skips_empty_turns(self, monkeypatch):
        payload = (
            '{"dialogue": [{"speaker": "Ana", "text": "Hola"}, '
            '{"speaker": "Marco", "text": ""}], "comprehension": null}'
        )
        monkeypatch.setattr(peer, "get_provider", lambda tier: FakeProvider(payload))
        result = await peer.generate_peer_dialogue("Spanish")
        assert len(result["dialogue"]) == 1

    async def test_llm_failure_returns_empty(self, monkeypatch):
        class Boom(LLMProvider):
            name = "boom"

            def is_available(self):
                return True

            async def generate(self, *a, **k):
                raise RuntimeError("down")

        monkeypatch.setattr(peer, "get_provider", lambda tier: Boom())
        result = await peer.generate_peer_dialogue("Spanish")
        assert result["dialogue"] == []
        assert result["comprehension"] is None


class TestFormat:
    def test_renders_dialogue_and_question(self):
        result = {
            "dialogue": [{"speaker": "Ana", "text": "Hola"}],
            "comprehension": {"question": "Who spoke?", "answer": "Ana"},
        }
        text = peer.format_peer_dialogue(result)
        assert "Ana: Hola" in text
        assert "Who spoke?" in text

    def test_empty_dialogue(self):
        assert peer.format_peer_dialogue({"dialogue": []}) == "No dialogue available."
