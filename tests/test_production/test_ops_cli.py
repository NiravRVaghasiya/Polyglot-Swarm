"""The operator CLI (`polyglot ops ...`) used by the runbook."""

from __future__ import annotations

from typer.testing import CliRunner

from src.cli import app
from src.config import settings
from src.memory import schema
from src.ops import backup

runner = CliRunner()


def test_backup_verify_and_restore_guard(temp_storage, monkeypatch):
    schema.init_all()
    monkeypatch.setattr(settings, "backup_retention_count", 1)
    assert runner.invoke(app, ["ops", "backup", "--label", "a"]).exit_code == 0
    assert runner.invoke(app, ["ops", "backup", "--label", "b"]).exit_code == 0
    sets = backup.list_backup_sets()
    assert len(sets) == 1 and sets[0].name.endswith("-b")  # retention applied
    assert "users" in runner.invoke(app, ["ops", "backups"]).output
    assert runner.invoke(app, ["ops", "verify", str(sets[0])]).exit_code == 0
    # Restore refuses without an explicit confirmation that the API is stopped.
    assert runner.invoke(app, ["ops", "restore", str(sets[0])]).exit_code == 2
    assert runner.invoke(app, ["ops", "restore", str(sets[0]), "--yes"]).exit_code == 0


def test_db_check_fails_on_schema_drift(temp_storage):
    schema.init_all()
    assert runner.invoke(app, ["ops", "db-check"]).exit_code == 0
    from src.memory.db import get_connection

    with get_connection() as conn:
        conn.execute("PRAGMA user_version = 3")
    assert runner.invoke(app, ["ops", "db-check"]).exit_code == 1


def test_config_check_reports_production_problems(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    result = runner.invoke(app, ["ops", "config-check"])
    assert result.exit_code == 1 and "METRICS_TOKEN" in result.output


def test_maintenance_runs(temp_storage):
    result = runner.invoke(app, ["ops", "maintenance"])
    assert result.exit_code == 0 and "expired_tokens" in result.output
