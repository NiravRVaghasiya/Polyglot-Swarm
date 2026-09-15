"""Phase 22 tests: scenario-load caching (by path + mtime)."""

from __future__ import annotations

import time

import pytest

from src.scenarios import loader
from src.scenarios.loader import clear_scenario_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Every test starts and ends with a clean scenario cache — the cache is
    process-global (an lru_cache), so tests must not leak state into each
    other via stale/duplicate cache entries across different tmp_path files."""
    clear_scenario_cache()
    yield
    clear_scenario_cache()


_VALID_YAML = """
scenario:
  id: "cache_test"
  title: "Test"
  language: "es"
  persona:
    name: "Ana"
    role: "waiter"
"""


class TestScenarioIsCached:
    def test_repeated_loads_return_the_same_object(self, tmp_path):
        f = tmp_path / "s.yaml"
        f.write_text(_VALID_YAML, encoding="utf-8")

        first = loader.load_scenario_file(f)
        second = loader.load_scenario_file(f)

        assert first is second  # identity, not just equality: proves the cache hit

    def test_cache_info_shows_a_hit_on_the_second_load(self, tmp_path):
        f = tmp_path / "s.yaml"
        f.write_text(_VALID_YAML, encoding="utf-8")

        loader.load_scenario_file(f)
        loader.load_scenario_file(f)

        info = loader._load_scenario_file_cached.cache_info()
        assert info.hits >= 1

    def test_different_files_are_cached_independently(self, tmp_path):
        f1 = tmp_path / "a.yaml"
        f2 = tmp_path / "b.yaml"
        f1.write_text(_VALID_YAML, encoding="utf-8")
        f2.write_text(_VALID_YAML.replace("cache_test", "other_test"), encoding="utf-8")

        a = loader.load_scenario_file(f1)
        b = loader.load_scenario_file(f2)

        assert a.id == "cache_test"
        assert b.id == "other_test"
        assert a is not b


class TestScenarioCacheInvalidatesOnEdit:
    def test_editing_the_file_picks_up_the_new_content(self, tmp_path):
        f = tmp_path / "s.yaml"
        f.write_text(_VALID_YAML, encoding="utf-8")
        first = loader.load_scenario_file(f)
        assert first.persona.name == "Ana"

        # Ensure a distinct mtime (some filesystems have coarse resolution).
        time.sleep(0.02)
        edited = _VALID_YAML.replace('name: "Ana"', 'name: "Carlos"')
        f.write_text(edited, encoding="utf-8")
        # Force the mtime forward explicitly so the test doesn't depend on
        # filesystem timestamp resolution.
        new_mtime = f.stat().st_mtime + 1.0
        import os

        os.utime(f, (new_mtime, new_mtime))

        second = loader.load_scenario_file(f)
        assert second.persona.name == "Carlos"
        assert second is not first


class TestClearScenarioCache:
    def test_clear_forces_a_fresh_parse(self, tmp_path):
        f = tmp_path / "s.yaml"
        f.write_text(_VALID_YAML, encoding="utf-8")

        first = loader.load_scenario_file(f)
        clear_scenario_cache()
        second = loader.load_scenario_file(f)

        assert first is not second
        assert first == second  # same content, different object identity


class TestMissingFileNotCached:
    def test_missing_file_is_not_cached_and_appearing_later_works(self, tmp_path):
        f = tmp_path / "appears-later.yaml"
        with pytest.raises(loader.ScenarioError, match="not found"):
            loader.load_scenario_file(f)

        f.write_text(_VALID_YAML, encoding="utf-8")
        # Must succeed now — the earlier failed lookup must not have been
        # cached in a way that makes this raise again.
        scenario = loader.load_scenario_file(f)
        assert scenario.id == "cache_test"
