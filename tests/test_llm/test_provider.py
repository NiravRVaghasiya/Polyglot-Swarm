"""Tests for the provider interface helpers and the Claude provider."""

from __future__ import annotations

from src.llm.claude import ClaudeProvider
from src.llm.provider import (
    JSON_MODE_INSTRUCTION,
    Message,
    apply_json_mode,
)


class TestApplyJsonMode:
    def test_appends_to_existing_system_message(self):
        msgs = [Message("system", "Be helpful."), Message("user", "hi")]
        out = apply_json_mode(msgs)

        assert out[0].role == "system"
        assert "Be helpful." in out[0].content
        assert JSON_MODE_INSTRUCTION in out[0].content
        # User message preserved and unchanged.
        assert out[1] == Message("user", "hi")

    def test_prepends_system_message_when_absent(self):
        msgs = [Message("user", "hi")]
        out = apply_json_mode(msgs)

        assert out[0].role == "system"
        assert out[0].content == JSON_MODE_INSTRUCTION
        assert out[1] == Message("user", "hi")

    def test_only_injects_once(self):
        msgs = [
            Message("system", "A"),
            Message("system", "B"),
            Message("user", "hi"),
        ]
        out = apply_json_mode(msgs)
        system_msgs = [m for m in out if m.role == "system"]
        injected = [m for m in system_msgs if JSON_MODE_INSTRUCTION in m.content]
        assert len(injected) == 1


class TestClaudeProviderAvailability:
    def test_unavailable_without_key(self):
        provider = ClaudeProvider(api_key="")
        assert provider.is_available() is False

    def test_available_with_key(self):
        provider = ClaudeProvider(api_key="sk-ant-test")
        assert provider.is_available() is True

    def test_defaults_model_from_settings(self):
        from src.config import settings

        provider = ClaudeProvider(api_key="k")
        assert provider.model == settings.llm_primary


class TestClaudeProviderGenerate:
    async def test_maps_messages_and_params(self, fake_langchain):
        provider = ClaudeProvider(model="claude-test", api_key="sk-ant-test")
        messages = [
            Message("system", "You are a tutor."),
            Message("user", "Hola"),
        ]

        result = await provider.generate(messages, temperature=0.3, max_tokens=123)

        assert result == "canned reply"

        model = fake_langchain.last_instance
        # Constructor received the right params.
        assert model.init_kwargs["model"] == "claude-test"
        assert model.init_kwargs["api_key"] == "sk-ant-test"
        assert model.init_kwargs["temperature"] == 0.3
        assert model.init_kwargs["max_tokens"] == 123
        # Messages mapped in order to LangChain message objects.
        assert [m.content for m in model.invoked_with] == [
            "You are a tutor.",
            "Hola",
        ]

    async def test_json_mode_injects_instruction(self, fake_langchain):
        provider = ClaudeProvider(api_key="sk-ant-test")
        messages = [Message("user", "give me json")]

        await provider.generate(messages, json_mode=True)

        model = fake_langchain.last_instance
        contents = [m.content for m in model.invoked_with]
        assert any(JSON_MODE_INSTRUCTION in c for c in contents)

    async def test_normalizes_list_content_blocks(self, fake_langchain):
        provider = ClaudeProvider(api_key="sk-ant-test")

        # First construct via generate to get the instance, then override reply.
        messages = [Message("user", "hi")]
        # Patch the recording model instance to return block-style content.
        result_holder = {}

        original_ainvoke = fake_langchain.ainvoke

        async def blocky_ainvoke(self, msgs):  # noqa: ANN001
            from tests.test_llm.conftest import FakeResponse

            result_holder["called"] = True
            return FakeResponse(content=[{"text": "part1"}, {"text": "part2"}])

        fake_langchain.ainvoke = blocky_ainvoke
        try:
            out = await provider.generate(messages)
        finally:
            fake_langchain.ainvoke = original_ainvoke

        assert out == "part1part2"
        assert result_holder.get("called") is True
