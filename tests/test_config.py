"""Tests for configuration loading, validation, and .env.example sync.

These guard Phase 0's ".env.example validation" acceptance item: the example
file must stay in sync with the ``Settings`` schema, and the app must refuse to
run with no usable LLM backend (outside deterministic mode).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.config import Settings, validate_settings

_ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# Keys documented in .env.example that are intentionally NOT Settings fields
# (voice/optional integrations wired elsewhere).
_ALLOWED_EXTRA_ENV_KEYS = {
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
}


def _env_example_keys() -> set[str]:
    keys: set[str] = set()
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([A-Z0-9_]+)=", line)
        if match:
            keys.add(match.group(1))
    return keys


class TestEnvExampleSync:
    def test_env_example_exists(self):
        assert _ENV_EXAMPLE.exists()

    def test_every_env_example_key_maps_to_a_setting(self):
        settings_keys = {name.upper() for name in Settings.model_fields}
        documented = _env_example_keys()
        unknown = documented - settings_keys - _ALLOWED_EXTRA_ENV_KEYS
        assert not unknown, (
            f".env.example documents keys with no matching Settings field: {unknown}"
        )


class TestValidation:
    def test_no_backend_is_a_problem_outside_deterministic(self, monkeypatch):
        monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)
        s = Settings(
            anthropic_api_key="",
            google_api_key="",
            openai_api_key="",
            ollama_base_url="",
        )
        problems = validate_settings(s)
        assert problems
        with pytest.raises(RuntimeError):
            validate_settings(s, strict=True)

    def test_hosted_key_satisfies_validation(self, monkeypatch):
        monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)
        s = Settings(anthropic_api_key="sk-ant-x", ollama_base_url="")
        assert validate_settings(s) == []
        assert "claude" in s.configured_backends()

    def test_deterministic_mode_satisfies_validation(self, monkeypatch):
        monkeypatch.setenv("POLYGLOT_DETERMINISTIC", "1")
        s = Settings(
            anthropic_api_key="",
            google_api_key="",
            openai_api_key="",
            ollama_base_url="",
        )
        assert validate_settings(s) == []
        assert "deterministic" in s.configured_backends()

    def test_invalid_retention_rejected(self):
        with pytest.raises(ValueError):
            Settings(fsrs_desired_retention=1.5)
