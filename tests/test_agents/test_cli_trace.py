"""Tests for the CLI `trace` command (Phase 17 observability)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.config import settings


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    return data_dir


def test_trace_command_no_data(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["trace", "no-such-session", "--user", "u1"])
    assert result.exit_code == 0
    assert "no recorded spans" in result.stdout


def test_trace_command_renders_spans(temp_storage):
    from src.cli import app
    from src.evidence.events import EventType, LearningEvent
    from src.evidence.provenance import Provenance
    from src.evidence.store import record_events
    from src.llm.telemetry import ModelRun
    from src.memory.model_runs import record_run

    record_events(
        [
            LearningEvent.create(
                EventType.TURN_COMPLETED,
                "u1",
                "Spanish",
                provenance=Provenance(source="test", session_id="s1", interaction_id="iid-1"),
                observed="hola",
            )
        ]
    )
    record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-1"))

    result = CliRunner().invoke(app, ["trace", "s1", "--user", "u1"])
    assert result.exit_code == 0
    assert "iid-1" in result.stdout
    assert "evidence" in result.stdout
    assert "model_run" in result.stdout
