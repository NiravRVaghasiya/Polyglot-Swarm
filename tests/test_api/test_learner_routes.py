"""Phase 16 tests: learner-model API routes (plan/cefr/skill-map/insights)."""

from __future__ import annotations


def _seed(user_id: str, language: str = "Spanish") -> None:
    from src.learner import get_knowledge_model
    from src.memory import analytics

    get_knowledge_model().update_from_events(
        user_id,
        language,
        [{"skill": "vocabulary", "assessment": "correct", "confidence": 0.9} for _ in range(6)],
    )
    get_knowledge_model().update_from_events(
        user_id,
        language,
        [{"skill": "grammar", "assessment": "incorrect", "confidence": 0.9} for _ in range(3)],
    )
    analytics.record_error(user_id, language, "ser_vs_estar")


class TestPlanRoute:
    def test_plan_returns_actions(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        resp = client.get("/api/v1/learner/plan?language=Spanish", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["language"] == "Spanish"
        assert body["actions"]
        assert {"type", "target", "reason", "priority"} <= set(body["actions"][0])

    def test_plan_honors_goal_and_minutes(self, auth_client):
        client, headers, user_id = auth_client
        resp = client.get(
            "/api/v1/learner/plan?language=Spanish&goal=reading&minutes=5", headers=headers
        )
        assert resp.status_code == 200
        assert resp.json()["goal"] == "reading"

    def test_plan_requires_auth(self, client):
        assert client.get("/api/v1/learner/plan").status_code == 401


class TestCEFRRoute:
    def test_cefr_profile(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        resp = client.get("/api/v1/learner/cefr?language=Spanish", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["language"] == "Spanish"
        assert "overall" in body
        assert "vocabulary" in body["skills"]
        assert body["skills"]["vocabulary"]["cefr"] in ("C1", "C2")

    def test_cefr_empty_learner(self, auth_client):
        client, headers, _ = auth_client
        resp = client.get("/api/v1/learner/cefr?language=Spanish", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["skills"] == {}


class TestSkillMapRoute:
    def test_skill_map(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        resp = client.get("/api/v1/learner/skill-map?language=Spanish", headers=headers)
        assert resp.status_code == 200
        skills = {s["skill"] for s in resp.json()["skills"]}
        assert {"grammar", "vocabulary"} <= skills
        for s in resp.json()["skills"]:
            assert 0.0 <= s["mastery"] <= 1.0
            assert 0.0 <= s["uncertainty"] <= 1.0


class TestInsightsRoute:
    def test_insights(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        resp = client.get("/api/v1/learner/insights?language=Spanish", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "overall_cefr" in body
        assert isinstance(body["weakest_skills"], list)
        assert isinstance(body["recommended_focus"], list)

    def test_insights_requires_auth(self, client):
        assert client.get("/api/v1/learner/insights").status_code == 401


class TestCEFRHistoryRoute:
    def test_cefr_history(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import analytics

        analytics.log_session(user_id, "Spanish", cefr_estimate="A2")
        resp = client.get("/api/v1/learner/cefr-history?language=Spanish", headers=headers)
        assert resp.status_code == 200
        assert "progression" in resp.json()
