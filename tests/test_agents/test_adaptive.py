"""Tests for the adaptive difficulty engine."""

from __future__ import annotations

from src.agents import adaptive
from src.agents.adaptive import adaptive_node, guidance_for_level, next_level


class TestNextLevel:
    def test_too_hard_steps_down(self):
        assert next_level("B1", "too_hard") == "A2"

    def test_too_easy_steps_up(self):
        assert next_level("B1", "too_easy") == "B2"

    def test_appropriate_unchanged(self):
        assert next_level("B1", "appropriate") == "B1"

    def test_clamps_at_bottom(self):
        assert next_level("A1", "too_hard") == "A1"

    def test_clamps_at_top(self):
        assert next_level("C2", "too_easy") == "C2"

    def test_unknown_level_defaults(self):
        # Unknown current level is treated as A2 (index 1).
        assert next_level("ZZ", "too_easy") == "B1"


class TestGuidance:
    def test_guidance_differs_by_level(self):
        assert guidance_for_level("A1") != guidance_for_level("C1")

    def test_unknown_level_falls_back(self):
        assert guidance_for_level("ZZ") == guidance_for_level("A2")


class TestAdaptiveNode:
    def _state(self, level="B1", difficulty="appropriate"):
        return {
            "cefr_level": level,
            "current_scenario": {"persona": {"name": "Ana"}},
            "evaluation": {"difficulty_assessment": difficulty},
        }

    def test_steps_down_on_too_hard(self):
        result = adaptive_node(self._state("B1", "too_hard"))
        assert result["cefr_level"] == "A2"
        assert "difficulty_guidance" in result["current_scenario"]

    def test_steps_up_on_too_easy(self):
        result = adaptive_node(self._state("A2", "too_easy"))
        assert result["cefr_level"] == "B1"

    def test_appropriate_keeps_level(self):
        result = adaptive_node(self._state("B1", "appropriate"))
        assert result["cefr_level"] == "B1"

    def test_no_evaluation_keeps_level(self):
        state = {"cefr_level": "B1", "current_scenario": {}, "evaluation": None}
        result = adaptive_node(state)
        assert result["cefr_level"] == "B1"

    def test_preserves_scenario_fields(self):
        result = adaptive_node(self._state("B1", "too_easy"))
        # Persona (and other scenario data) survive the update.
        assert result["current_scenario"]["persona"]["name"] == "Ana"

    def test_guidance_matches_new_level(self):
        result = adaptive_node(self._state("A2", "too_easy"))
        assert result["current_scenario"]["difficulty_guidance"] == adaptive.guidance_for_level("B1")
