"""Verify conversation/grammar/vocabulary agents use the LLM provider factory.

These tests confirm the Phase 0 migration: agents no longer construct a vendor
SDK directly, they request a routing provider by tier and call
``await provider.generate(...)``. All LLM calls are mocked — no network.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.agents import conversation, grammar, vocabulary
from src.llm.provider import LLMProvider, Message

SRC = Path(__file__).resolve().parents[2] / "src" / "agents"


class FakeProvider(LLMProvider):
    """Records how it was called and returns a canned reply."""

    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            }
        )
        return self.reply


def _base_state(**overrides):
    state = {
        "session_id": "s1",
        "language": "Spanish",
        "mode": "conversation",
        "messages": [],
        "current_scenario": {
            "persona": {"name": "Ana", "role": "waiter", "personality": "warm"},
            "location": "Madrid",
            "objectives": ["order food"],
            "context": "restaurant",
        },
        "current_persona": None,
        "grammar_errors": [],
        "new_vocabulary": [],
        "cultural_notes": [],
        "evaluation": None,
        "cefr_level": "A2",
        "vocabulary_known_count": 0,
        "grammar_weaknesses": [],
        "user_interests": [],
        "turn_count": 0,
        "should_end_session": False,
        "pending_reviews": [],
        "last_user_input": "Hola, una mesa para dos",
        "agent_response": "",
    }
    state.update(overrides)
    return state


class TestNoDirectSdkImports:
    """Static guard: agents must not import a concrete LLM SDK anymore."""

    @pytest.mark.parametrize("module_file", ["conversation.py", "grammar.py", "vocabulary.py"])
    def test_no_vendor_sdk_import(self, module_file):
        source = (SRC / module_file).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)

        forbidden = {
            "langchain_anthropic",
            "langchain_google_genai",
            "langchain_community",
            "langchain_openai",
            "openai",
            "anthropic",
        }
        assert not (imported & forbidden), (
            f"{module_file} imports a vendor SDK: {imported & forbidden}"
        )
        # And it should depend on the factory.
        assert "src.llm.factory" in imported


class TestConversationAgent:
    async def test_uses_primary_tier(self, monkeypatch):
        fake = FakeProvider("¡Bienvenido! ¿Mesa para cuántos?")
        captured = {}

        def fake_get_provider(tier):
            captured["tier"] = tier
            return fake

        monkeypatch.setattr(conversation, "get_provider", fake_get_provider)

        result = await conversation.conversation_node(_base_state())

        assert captured["tier"] == "primary"
        assert result["agent_response"] == "¡Bienvenido! ¿Mesa para cuántos?"
        assert result["turn_count"] == 1
        # User + assistant appended to messages.
        roles = [m["role"] for m in result["messages"]]
        assert roles == ["user", "assistant"]
        # System prompt is the first message sent to the provider.
        sent = fake.calls[0]["messages"]
        assert isinstance(sent[0], Message) and sent[0].role == "system"
        assert fake.calls[0]["temperature"] == 0.8
        assert fake.calls[0]["max_tokens"] == 300


class TestGrammarAgent:
    async def test_uses_fast_tier_json_mode(self, monkeypatch):
        fake = FakeProvider('{"errors": []}')
        captured = {}
        monkeypatch.setattr(
            grammar,
            "get_provider",
            lambda tier: captured.update(tier=tier) or fake,
        )

        result = await grammar.grammar_node(_base_state())

        assert captured["tier"] == "fast"
        assert fake.calls[0]["json_mode"] is True
        assert fake.calls[0]["temperature"] == 0.0
        assert result["grammar_errors"] == []

    async def test_parses_errors(self, monkeypatch):
        payload = (
            '{"errors": [{"original": "Yo soy hambre", "correction": "Yo tengo hambre",'
            ' "rule": "ser_vs_tener", "explanation": "use tener", "severity": "moderate"}]}'
        )
        monkeypatch.setattr(grammar, "get_provider", lambda tier: FakeProvider(payload))

        result = await grammar.grammar_node(_base_state())
        assert len(result["grammar_errors"]) == 1
        assert result["grammar_errors"][0]["rule"] == "ser_vs_tener"

    async def test_skips_short_input(self, monkeypatch):
        called = {"n": 0}

        def boom(tier):
            called["n"] += 1
            raise AssertionError("should not call provider for short input")

        monkeypatch.setattr(grammar, "get_provider", boom)
        result = await grammar.grammar_node(_base_state(last_user_input="ok"))
        assert result["grammar_errors"] == []
        assert called["n"] == 0


class TestVocabularyAgent:
    async def test_uses_fast_tier_json_mode(self, monkeypatch):
        payload = (
            '{"words": [{"word": "mesa", "translation": "table", "pos": "noun",'
            ' "context_sentence": "una mesa para dos"}]}'
        )
        captured = {}
        fake = FakeProvider(payload)
        monkeypatch.setattr(
            vocabulary,
            "get_provider",
            lambda tier: captured.update(tier=tier) or fake,
        )

        result = await vocabulary.vocabulary_node(
            _base_state(agent_response="¿Prefiere una mesa cerca de la ventana?")
        )

        assert captured["tier"] == "fast"
        assert fake.calls[0]["json_mode"] is True
        assert len(result["new_vocabulary"]) == 1
        assert result["new_vocabulary"][0]["word"] == "mesa"
