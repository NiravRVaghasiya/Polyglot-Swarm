"""Tests for the Gemini and Ollama providers."""

from __future__ import annotations

from src.llm.gemini import GeminiProvider
from src.llm.ollama import OllamaProvider, _strip_provider_prefix
from src.llm.provider import JSON_MODE_INSTRUCTION, Message


class TestGeminiAvailability:
    def test_unavailable_without_key(self):
        assert GeminiProvider(api_key="").is_available() is False

    def test_available_with_key(self):
        assert GeminiProvider(api_key="AIza-test").is_available() is True

    def test_defaults_model_from_settings(self):
        from src.config import settings

        assert GeminiProvider(api_key="k").model == settings.llm_fast


class TestGeminiGenerate:
    async def test_maps_messages_and_params(self, fake_langchain):
        provider = GeminiProvider(model="gemini-test", api_key="AIza-test")
        messages = [Message("system", "sys"), Message("user", "hi")]

        result = await provider.generate(messages, temperature=0.5, max_tokens=64)

        assert result == "canned reply"
        model = fake_langchain.last_instance
        assert model.init_kwargs["model"] == "gemini-test"
        assert model.init_kwargs["google_api_key"] == "AIza-test"
        assert model.init_kwargs["temperature"] == 0.5
        assert model.init_kwargs["max_output_tokens"] == 64
        assert [m.content for m in model.invoked_with] == ["sys", "hi"]

    async def test_json_mode(self, fake_langchain):
        provider = GeminiProvider(api_key="AIza-test")
        await provider.generate([Message("user", "json please")], json_mode=True)

        model = fake_langchain.last_instance
        assert any(JSON_MODE_INSTRUCTION in m.content for m in model.invoked_with)


class TestOllamaStripPrefix:
    def test_strips_ollama_prefix(self):
        assert _strip_provider_prefix("ollama/llama3.1:8b") == "llama3.1:8b"

    def test_leaves_bare_name(self):
        assert _strip_provider_prefix("llama3.1:8b") == "llama3.1:8b"


class TestOllamaAvailability:
    def test_available_with_base_url(self):
        assert OllamaProvider(base_url="http://localhost:11434").is_available() is True

    def test_unavailable_without_base_url(self):
        assert OllamaProvider(base_url="").is_available() is False


class TestOllamaGenerate:
    async def test_maps_messages_and_params(self, fake_langchain):
        provider = OllamaProvider(model="ollama/llama3.1:8b", base_url="http://localhost:11434")
        messages = [Message("system", "sys"), Message("user", "cześć")]

        result = await provider.generate(messages, temperature=0.2, max_tokens=32)

        assert result == "canned reply"
        model = fake_langchain.last_instance
        # Prefix stripped before reaching the client.
        assert model.init_kwargs["model"] == "llama3.1:8b"
        assert model.init_kwargs["base_url"] == "http://localhost:11434"
        assert model.init_kwargs["temperature"] == 0.2
        assert model.init_kwargs["num_predict"] == 32
        assert [m.content for m in model.invoked_with] == ["sys", "cześć"]
