"""Tests for wiring scenarios into the orchestrator and CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.config import settings
from src.orchestrator.lifecycle import build_initial_state


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


class TestBuildInitialStateWithScenario:
    def test_loads_scenario_persona_and_objectives(self, temp_storage):
        state = build_initial_state("u1", scenario_id="es_restaurant_ordering")
        scenario = state["current_scenario"]
        assert scenario["scenario_id"] == "es_restaurant_ordering"
        assert scenario["persona"]["name"] == "Carlos"
        assert any("table" in o.lower() or "order" in o.lower() for o in scenario["objectives"])

    def test_language_derived_from_scenario(self, temp_storage):
        # es_* scenario -> Spanish (the free-form name the agents use).
        state = build_initial_state("u1", scenario_id="it_bar_caffe")
        assert state["language"] == "Italian"

    def test_explicit_language_overrides(self, temp_storage):
        state = build_initial_state("u1", "Spanish", scenario_id="es_restaurant_ordering")
        assert state["language"] == "Spanish"

    def test_difficulty_guidance_present(self, temp_storage):
        state = build_initial_state("u1", scenario_id="es_restaurant_ordering")
        # Profile defaults to A2, which the restaurant scenario defines guidance for.
        assert state["current_scenario"]["difficulty_guidance"]

    def test_no_scenario_uses_default(self, temp_storage):
        state = build_initial_state("u1", "Spanish")
        assert state["current_scenario"]["persona"]["role"] == "friendly local"


class TestCli:
    def test_scenarios_command_lists(self):
        from src.cli import app

        result = CliRunner().invoke(app, ["scenarios", "--language", "it"])
        assert result.exit_code == 0
        assert "it_bar_caffe" in result.stdout

    def test_scenarios_command_all(self):
        from src.cli import app

        result = CliRunner().invoke(app, ["scenarios"])
        assert result.exit_code == 0
        assert "es_restaurant_ordering" in result.stdout
