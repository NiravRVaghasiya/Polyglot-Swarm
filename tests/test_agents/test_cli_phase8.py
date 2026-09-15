"""Smoke tests for the Phase 8 CLI commands (peer, write, ingest)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    return data_dir


@pytest.fixture(autouse=True)
def mock_providers(monkeypatch):
    """Patch each Phase 8 agent's provider so CLI commands run offline."""
    from src.agents import ingestion, peer, writing
    from src.llm.provider import LLMProvider

    class Scripted(LLMProvider):
        name = "scripted"

        def __init__(self, reply: str):
            self.reply = reply

        def is_available(self) -> bool:
            return True

        async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
            return self.reply

    monkeypatch.setattr(
        peer,
        "get_provider",
        lambda tier: Scripted(
            '{"dialogue": [{"speaker": "Ana", "text": "Hola"}], '
            '"comprehension": {"question": "Who?", "answer": "Ana"}}'
        ),
    )
    monkeypatch.setattr(
        writing,
        "get_provider",
        lambda tier: Scripted(
            '{"corrections": [], "style_notes": [], "overall": "Great!", "corrected_text": "ok"}'
        ),
    )
    monkeypatch.setattr(
        ingestion,
        "get_provider",
        lambda tier: Scripted(
            '{"simplified": "El gato.", "vocab": '
            '[{"word": "gato", "translation": "cat", "pos": "noun"}]}'
        ),
    )


def test_peer_command(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["peer", "--user", "u1", "--language", "Spanish"])
    assert result.exit_code == 0
    assert "Ana: Hola" in result.stdout


def test_write_command(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["write", "hola mundo", "--user", "u1"])
    assert result.exit_code == 0
    assert "Great!" in result.stdout


def test_ingest_command(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["ingest", "un articulo largo", "--user", "u1"])
    assert result.exit_code == 0
    assert "El gato." in result.stdout
    assert "1 word" in result.stdout

    from src.memory import vocabulary_db

    assert any(w["word"] == "gato" for w in vocabulary_db.get_all_for_user("u1", "Spanish"))
