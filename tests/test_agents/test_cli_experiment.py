"""Tests for the `polyglot experiment ...` CLI commands (Phase 19)."""

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


def test_create_command_runs(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(
        app, ["experiment", "create", "demo", "--variants", "control,treatment"]
    )
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "control" in result.stdout
    assert "treatment" in result.stdout


def test_assign_command_runs(temp_storage):
    from src.cli import app

    CliRunner().invoke(app, ["experiment", "create", "demo", "--variants", "control,treatment"])
    result = CliRunner().invoke(app, ["experiment", "assign", "demo", "--user", "u1"])
    assert result.exit_code == 0
    assert "u1" in result.stdout


def test_assign_unknown_experiment_fails_gracefully(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["experiment", "assign", "no-such-experiment", "--user", "u1"])
    assert result.exit_code == 1
    assert "unknown experiment" in result.stdout


def test_measure_records_an_outcome(temp_storage):
    from src.cli import app
    from src.memory import experiments

    CliRunner().invoke(app, ["experiment", "create", "demo", "--variants", "control,treatment"])
    CliRunner().invoke(app, ["experiment", "assign", "demo", "--user", "u1"])
    result = CliRunner().invoke(
        app,
        ["experiment", "measure", "demo", "--user", "u1", "--point", "pre_test"],
    )
    assert result.exit_code == 0
    assert "pre_test" in result.stdout
    rows = experiments.get_outcomes("demo", user_id="u1")
    assert len(rows) == 1
    assert rows[0]["measurement_point"] == "pre_test"
    assert rows[0]["metric"] == "overall_cefr_ordinal"


def test_measure_without_assignment_fails_gracefully(temp_storage):
    from src.cli import app

    CliRunner().invoke(app, ["experiment", "create", "demo", "--variants", "a,b"])
    result = CliRunner().invoke(
        app, ["experiment", "measure", "demo", "--user", "unassigned", "--point", "pre_test"]
    )
    assert result.exit_code == 1
    assert "no variant assignment" in result.stdout


def test_report_with_no_data(temp_storage):
    from src.cli import app

    CliRunner().invoke(app, ["experiment", "create", "demo", "--variants", "a,b"])
    result = CliRunner().invoke(app, ["experiment", "report", "demo"])
    assert result.exit_code == 0
    assert "No outcomes recorded" in result.stdout


def test_report_shows_recorded_outcomes(temp_storage):
    from src.cli import app

    CliRunner().invoke(app, ["experiment", "create", "demo", "--variants", "control"])
    CliRunner().invoke(app, ["experiment", "assign", "demo", "--user", "u1"])
    CliRunner().invoke(
        app, ["experiment", "measure", "demo", "--user", "u1", "--point", "pre_test"]
    )
    result = CliRunner().invoke(app, ["experiment", "report", "demo"])
    assert result.exit_code == 0
    assert "control" in result.stdout
    assert "pre_test" in result.stdout


def test_ablation_command_runs_and_reports_gain(temp_storage):
    from src.cli import app

    result = CliRunner().invoke(app, ["experiment", "ablation", "--learners", "1"])
    assert result.exit_code == 0, result.stdout
    # Every arm appears in the rendered table, and the analysis arms gain.
    for arm in ("A", "B", "C", "D", "E"):
        assert arm in result.stdout
    assert "gain" in result.stdout


def test_due_command_empty_right_after_assignment(temp_storage):
    from src.cli import app

    CliRunner().invoke(app, ["experiment", "create", "exp", "--variants", "control"])
    CliRunner().invoke(app, ["experiment", "assign", "exp", "--user", "u1"])

    result = CliRunner().invoke(app, ["experiment", "due", "exp"])
    assert result.exit_code == 0
    assert "No delayed measurements are due" in result.stdout
