"""Tests for the live backend checks behind `polyglot health` and `chat`."""

from __future__ import annotations

import httpx
import pytest

from src.config import Settings
from src.llm import preflight


def _settings(**overrides) -> Settings:
    values = {
        "anthropic_api_key": "",
        "google_api_key": "",
        "openai_api_key": "",
        "ollama_base_url": "http://localhost:11434",
        "llm_local": "ollama/llama3.1:8b",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _tags(monkeypatch, *names: str) -> None:
    def fake_get(url, timeout):
        request = httpx.Request("GET", url)
        return httpx.Response(200, json={"models": [{"name": n} for n in names]}, request=request)

    monkeypatch.setattr(preflight.httpx, "get", fake_get)


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)


class TestOllama:
    def test_ready_when_model_is_pulled(self, monkeypatch):
        _tags(monkeypatch, "llama3.1:8b")
        [check] = preflight.check_backends(_settings())
        assert check.ok

    def test_untagged_model_matches_latest(self, monkeypatch):
        _tags(monkeypatch, "mistral:latest")
        [check] = preflight.check_backends(_settings(llm_local="ollama/mistral"))
        assert check.ok

    def test_missing_model_says_how_to_pull_it(self, monkeypatch):
        _tags(monkeypatch)
        [check] = preflight.check_backends(_settings())
        assert not check.ok
        assert "ollama pull llama3.1:8b" in check.fix

    def test_missing_model_suggests_an_installed_tag_of_it(self, monkeypatch):
        _tags(monkeypatch, "llama3.1:latest")
        [check] = preflight.check_backends(_settings())
        assert not check.ok
        assert "LLM_LOCAL=ollama/llama3.1:latest" in check.fix

    def test_missing_package_says_how_to_install_it(self, monkeypatch):
        _tags(monkeypatch, "llama3.1:8b")
        monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda name: None)
        [check] = preflight.check_backends(_settings())
        assert not check.ok
        assert "langchain-ollama" in check.detail
        assert "pip install" in check.fix

    def test_server_not_running(self, monkeypatch):
        def refuse(url, timeout):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(preflight.httpx, "get", refuse)
        [check] = preflight.check_backends(_settings())
        assert not check.ok
        assert "ollama.com" in check.fix


class TestOverall:
    def test_hosted_key_counts_as_usable(self, monkeypatch):
        _tags(monkeypatch)
        checks = preflight.check_backends(_settings(anthropic_api_key="sk-ant-x"))
        assert preflight.has_usable_backend(checks)

    def test_local_only_ignores_hosted_keys(self, monkeypatch):
        _tags(monkeypatch)
        checks = preflight.check_backends(_settings(anthropic_api_key="sk-ant-x", local_only=True))
        assert [c.name for c in checks] == ["ollama"]
        assert not preflight.has_usable_backend(checks)

    def test_nothing_configured_is_unusable(self):
        checks = preflight.check_backends(_settings(ollama_base_url=""))
        assert not preflight.has_usable_backend(checks)

    def test_deterministic_mode_is_usable(self, monkeypatch):
        monkeypatch.setenv("POLYGLOT_DETERMINISTIC", "1")
        checks = preflight.check_backends(_settings(ollama_base_url=""))
        assert preflight.has_usable_backend(checks)
