"""CLI setup experience: `health`, the `chat` preflight, and console encoding."""

from __future__ import annotations

import io

import pytest
from typer.testing import CliRunner

from src.config import settings
from src.llm.preflight import BackendCheck


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    return data_dir


@pytest.fixture
def no_backend(monkeypatch):
    """Live mode with nothing that can answer: no keys and Ollama not running."""
    from src.llm import preflight

    monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)
    monkeypatch.setattr(
        preflight,
        "check_backends",
        lambda s=None, **kw: [
            BackendCheck("ollama", False, "no Ollama server answering", "Install Ollama")
        ],
    )


def test_health_fails_with_fix_when_no_backend_works(no_backend):
    from src.cli import app

    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 1
    assert "Install Ollama" in result.stdout
    assert "POLYGLOT_DETERMINISTIC=1" in result.stdout


def test_health_passes_in_offline_demo_mode():
    from src.cli import app

    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    assert "Ready" in result.stdout


def test_chat_refuses_to_start_without_a_backend(no_backend, monkeypatch):
    from src import cli

    def must_not_start(*args, **kwargs):
        raise AssertionError("session started without a working backend")

    monkeypatch.setattr(cli, "build_initial_state", must_not_start)

    result = CliRunner().invoke(cli.app, ["chat"], input="Hola\nquit\n")

    assert result.exit_code == 1
    assert "No working LLM backend" in result.stdout


def test_chat_prints_bracketed_reply_text_verbatim(temp_storage):
    # Rich parsed replies as markup, so "[fake:ab12]" (and any "[word]" in a
    # real model's reply) vanished from the terminal.
    from src.cli import app

    result = CliRunner().invoke(
        app,
        ["chat", "--language", "Spanish", "--user", "u-cli-markup"],
        input="Usa [ser] aquí\nquit\n",
    )

    assert result.exit_code == 0, result.output
    assert "[fake:" in result.stdout
    assert "Usa [ser] aquí" in result.stdout


def test_non_utf8_console_is_switched_to_utf8():
    from src.cli import _ensure_utf8_output

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    _ensure_utf8_output(stream)

    stream.write("🌍 Polyglot Swarm")  # raised UnicodeEncodeError before the fix
    stream.flush()
    assert stream.encoding.lower().replace("-", "") == "utf8"


def test_ollama_context_default_fits_ordinary_machines():
    assert settings.ollama_num_ctx <= 8192
