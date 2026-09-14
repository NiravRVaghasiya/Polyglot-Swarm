"""Validate the entire shipped scenario library."""

from __future__ import annotations

import pytest

from src.scenarios import loader
from src.scenarios.loader import _iter_scenario_files


def _all_files():
    return _iter_scenario_files()


class TestLibraryIntegrity:
    def test_fifteen_scenarios(self):
        scenarios = loader.list_scenarios()
        assert len(scenarios) == 15

    def test_five_per_language(self):
        for lang in ("es", "pl", "it"):
            assert len(loader.list_scenarios(lang)) == 5, lang

    def test_all_ids_unique(self):
        ids = [s.id for s in loader.list_scenarios()]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("path", _all_files(), ids=lambda p: p.stem)
    def test_each_file_valid(self, path):
        scenario = loader.load_scenario_file(path)
        # Sanity: has a persona, at least one objective with required vocab,
        # difficulty scaling, and an opening line.
        assert scenario.persona.name
        assert scenario.objectives
        assert any(o.required_vocab for o in scenario.objectives)
        assert scenario.difficulty_scaling
        assert scenario.opening_line

    @pytest.mark.parametrize("path", _all_files(), ids=lambda p: p.stem)
    def test_language_matches_folder(self, path):
        scenario = loader.load_scenario_file(path)
        # Files live in a per-language folder; the scenario language should match.
        folder = path.parent.name
        if folder in ("es", "pl", "it"):
            assert scenario.language == folder
