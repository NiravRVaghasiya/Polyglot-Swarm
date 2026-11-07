"""One planner: /plan, /insights, /recommendations and `polyglot plan` agree."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from tests.test_api.test_adaptive_routes import _seed_grammar

ROOT = Path(__file__).parents[2]


def _actions(client, headers, **params):
    qs = "&".join(f"{k}={v}" for k, v in {"language": "Spanish", **params}.items())
    resp = client.get(f"/api/v1/learner/plan?{qs}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["actions"]


class TestOnePlanner:
    def test_plan_is_the_adaptive_engines_plan(self, auth_client):
        client, headers, user_id = auth_client
        _seed_grammar(user_id)
        actions = _actions(client, headers, record="false")
        full = client.get(
            "/api/v1/learner/recommendations?language=Spanish&record=false", headers=headers
        ).json()
        assert full["engine"] == "adaptive-nba-v1"
        assert [(a["type"], a["target"], a["intent"]) for a in actions] == [
            (r["activity"], r["target"], r["intent"]) for r in full["recommendations"]
        ]
        for a, r in zip(actions, full["recommendations"], strict=True):
            assert a["reason"] == r["rationale"][0]
            assert a["priority"] == round(r["score"], 3)
            assert set(a) == {
                "type",
                "target",
                "skill",
                "reason",
                "priority",
                "estimated_minutes",
                "intent",
            }

    def test_served_plan_is_recorded_and_preview_is_not(self, auth_client):
        client, headers, user_id = auth_client
        _seed_grammar(user_id)
        _actions(client, headers, record="false")
        assert client.get("/api/v1/learner/decisions", headers=headers).json()["decisions"] == []
        _actions(client, headers)
        [decision] = client.get("/api/v1/learner/decisions", headers=headers).json()["decisions"]
        assert decision["kind"] == "recommendation" and decision["engine"] == "adaptive-nba-v1"

    def test_insights_focus_comes_from_the_same_plan_without_recording(self, auth_client):
        client, headers, user_id = auth_client
        _seed_grammar(user_id)
        body = client.get("/api/v1/learner/insights?language=Spanish", headers=headers).json()
        reasons = [a["reason"] for a in _actions(client, headers, record="false")]
        assert body["recommended_focus"] == reasons[:3]
        assert client.get("/api/v1/learner/decisions", headers=headers).json()["decisions"] == []

    def test_cli_plan_uses_the_same_engine(self, auth_client):
        from src.adaptive.service import recommend
        from src.cli import app

        _client, _headers, user_id = auth_client
        _seed_grammar(user_id)
        result = CliRunner().invoke(app, ["plan", "--user", user_id, "--language", "Spanish"])
        assert result.exit_code == 0, result.output
        expected = recommend(user_id, "Spanish", record=False).plan.recommendations
        assert expected and all(r.activity in result.output for r in expected)

    def test_no_second_planner_remains(self):
        pattern = re.compile(r"plan_next_actions|curriculum\.planner")
        offenders = [
            str(p.relative_to(ROOT))
            for base in ("src", "frontend/react_app/src")
            for p in (ROOT / base).rglob("*")
            if p.suffix in {".py", ".ts", ".tsx"} and pattern.search(p.read_text(encoding="utf-8"))
        ]
        assert offenders == []
