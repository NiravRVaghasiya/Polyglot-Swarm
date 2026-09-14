"""Tests for the CLI drill and progress commands."""

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


def test_progress_command_runs(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["progress", "--user", "u1"])
    assert result.exit_code == 0
    assert "Progress for u1" in result.stdout


def test_drill_command_no_data(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["drill", "--user", "fresh", "--language", "Spanish"])
    assert result.exit_code == 0
    assert "No drills" in result.stdout
