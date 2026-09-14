"""Tests for the scenario schema, loader, and validation."""

from __future__ import annotations

import pytest

from src.scenarios import loader
from src.scenarios.loader import Scenario, ScenarioError


class TestLoadFile:
    def test_loads_valid_scenario(self, tmp_path):
        yaml_text = """
scenario:
  id: "es_test"
  title: "Test"
  language: "es"
  persona:
    name: "Ana"
    role: "waiter"
  objectives:
    - id: "greet"
      description: "Greet"
      required_vocab: ["hola", "mesa"]
  success_criteria:
    all_objectives_completed: true
    grammar_error_rate_max: 0.3
"""
        f = tmp_path / "s.yaml"
        f.write_text(yaml_text, encoding="utf-8")
        scenario = loader.load_scenario_file(f)
        assert isinstance(scenario, Scenario)
        assert scenario.id == "es_test"
        assert scenario.persona.name == "Ana"
        assert scenario.objectives[0].required_vocab == ["hola", "mesa"]
        assert scenario.success_criteria.grammar_error_rate_max == 0.3

    def test_missing_file(self, tmp_path):
        with pytest.raises(ScenarioError, match="not found"):
            loader.load_scenario_file(tmp_path / "nope.yaml")

    def test_malformed_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("scenario: [unclosed", encoding="utf-8")
        with pytest.raises(ScenarioError, match="malformed YAML"):
            loader.load_scenario_file(f)

    def test_missing_required_field(self, tmp_path):
        # No persona -> validation error.
        f = tmp_path / "s.yaml"
        f.write_text(
            'scenario:\n  id: "x"\n  title: "T"\n  language: "es"\n',
            encoding="utf-8",
        )
        with pytest.raises(ScenarioError, match="invalid scenario"):
            loader.load_scenario_file(f)

    def test_non_mapping_body(self, tmp_path):
        f = tmp_path / "s.yaml"
        f.write_text("scenario:\n  - just\n  - a list\n", encoding="utf-8")
        with pytest.raises(ScenarioError, match="expected a mapping"):
            loader.load_scenario_file(f)

    def test_accepts_bare_body_without_wrapper(self, tmp_path):
        # A file without the top-level "scenario:" key still parses.
        f = tmp_path / "s.yaml"
        f.write_text(
            'id: "bare"\ntitle: "T"\nlanguage: "it"\n'
            'persona:\n  name: "Marco"\n  role: "barista"\n',
            encoding="utf-8",
        )
        scenario = loader.load_scenario_file(f)
        assert scenario.id == "bare"


class TestShippedLibrary:
    def test_shipped_restaurant_loads(self):
        scenario = loader.get_scenario("es_restaurant_ordering")
        assert scenario.language == "es"
        assert len(scenario.objectives) == 4
        assert scenario.opening_line.startswith("¡Buenas tardes!")

    def test_scaling_for(self):
        scenario = loader.get_scenario("es_restaurant_ordering")
        assert "slowly" in scenario.scaling_for("A2").lower()
        assert scenario.scaling_for("C2") == ""  # not defined

    def test_get_unknown_scenario_raises(self):
        with pytest.raises(ScenarioError, match="No scenario with id"):
            loader.get_scenario("does_not_exist")

    def test_list_filter_by_language(self):
        es = loader.list_scenarios("es")
        assert all(s.language == "es" for s in es)
        assert any(s.id == "es_restaurant_ordering" for s in es)
