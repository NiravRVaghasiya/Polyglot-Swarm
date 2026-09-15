"""Phase 22 tests: session/user/turn cost aggregation (src.llm.cost)."""

from __future__ import annotations

import pytest

from src.config import settings
from src.llm.cost import session_cost, turn_cost, user_cost
from src.llm.telemetry import ModelRun
from src.memory.model_runs import record_run
from src.observability.links import record_link


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


def _run(**overrides):
    defaults = {
        "provider": "fake",
        "tier": "primary",
        "model": "m",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": 0.001,
        "success": True,
    }
    defaults.update(overrides)
    return ModelRun(**defaults)


class TestSessionCost:
    def test_empty_session_yields_zero_summary(self, temp_storage):
        summary = session_cost("no-such-session")
        assert summary.as_dict() == {
            "calls": 0,
            "tokens": 0,
            "cost_usd": 0.0,
            "mean_latency_ms": 0.0,
            "failures": 0,
            "by_tier": {},
        }

    def test_aggregates_runs_linked_to_the_session(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_run(_run(interaction_id="iid-1", cost_usd=0.002))
        record_run(_run(interaction_id="iid-1", tier="fast", cost_usd=0.001))

        summary = session_cost("s1")
        assert summary.calls == 2
        assert summary.tokens == 30
        assert round(summary.cost_usd, 6) == 0.003

    def test_excludes_runs_from_other_sessions(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_link("s2", "iid-2", user_id="u1")
        record_run(_run(interaction_id="iid-1"))
        record_run(_run(interaction_id="iid-2"))

        assert session_cost("s1").calls == 1
        assert session_cost("s2").calls == 1

    def test_by_tier_breakdown(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_run(_run(interaction_id="iid-1", tier="primary", cost_usd=0.01))
        record_run(_run(interaction_id="iid-1", tier="fast", cost_usd=0.001))
        record_run(_run(interaction_id="iid-1", tier="fast", cost_usd=0.001))

        summary = session_cost("s1")
        assert summary.by_tier["primary"]["calls"] == 1
        assert summary.by_tier["fast"]["calls"] == 2
        assert round(summary.by_tier["fast"]["cost_usd"], 6) == 0.002

    def test_counts_failures(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_run(_run(interaction_id="iid-1", success=True))
        record_run(_run(interaction_id="iid-1", success=False, error="boom"))

        summary = session_cost("s1")
        assert summary.failures == 1

    def test_scoped_by_user_id_when_given(self, temp_storage):
        # Another user's link to the same session id must not leak in.
        record_link("s1", "iid-other", user_id="u2")
        record_run(_run(interaction_id="iid-other"))

        assert session_cost("s1", user_id="u1").calls == 0
        assert session_cost("s1", user_id="u2").calls == 1
        assert session_cost("s1").calls == 1  # unscoped still finds it


class TestUserCost:
    def test_aggregates_across_sessions(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_link("s2", "iid-2", user_id="u1")
        record_run(_run(interaction_id="iid-1"))
        record_run(_run(interaction_id="iid-2"))

        assert user_cost("u1").calls == 2

    def test_excludes_other_users(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_link("s2", "iid-2", user_id="u2")
        record_run(_run(interaction_id="iid-1"))
        record_run(_run(interaction_id="iid-2"))

        assert user_cost("u1").calls == 1


class TestTurnCost:
    def test_aggregates_a_single_interaction(self, temp_storage):
        record_run(_run(interaction_id="iid-1"))
        record_run(_run(interaction_id="iid-1", tier="fast"))
        record_run(_run(interaction_id="iid-2"))  # a different turn

        assert turn_cost("iid-1").calls == 2

    def test_unknown_interaction_yields_empty_summary(self, temp_storage):
        assert turn_cost("no-such-interaction").calls == 0
