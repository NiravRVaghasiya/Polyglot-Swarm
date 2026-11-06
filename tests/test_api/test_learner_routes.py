"""Phase 16 tests: learner-model API routes (plan/cefr/skill-map/insights)."""

from __future__ import annotations


def _seed(user_id: str, language: str = "Spanish") -> None:
    from src.learner import get_knowledge_model
    from src.memory import analytics

    # Distinct items: identical dicts count once since ADR-0031.
    get_knowledge_model().update_from_events(
        user_id,
        language,
        [
            {"skill": "vocabulary", "assessment": "correct", "confidence": 0.9, "item_id": f"v{i}"}
            for i in range(6)
        ],
    )
    get_knowledge_model().update_from_events(
        user_id,
        language,
        [
            {"skill": "grammar", "assessment": "incorrect", "confidence": 0.9, "item_id": f"g{i}"}
            for i in range(3)
        ],
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
        body = resp.json()
        assert body["skills"] == {}
        # ADR-0031: no default level.
        assert body["overall"] is None
        assert body["overall_status"] == "insufficient_evidence"
        assert "speaking" in body["unassessed_skills"]

    def test_cefr_skill_carries_status_and_interval(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        body = client.get("/api/v1/learner/cefr?language=Spanish", headers=headers).json()
        vocab = body["skills"]["vocabulary"]
        assert vocab["status"] == "provisional"
        assert vocab["mastery_low"] < vocab["mastery"] < vocab["mastery_high"]
        assert vocab["independent_count"] == 6
        assert body["overall"] is not None
        assert body["method"] == "cefr-profile-v2"

    def test_insufficient_skill_has_null_band(self, auth_client):
        client, headers, user_id = auth_client
        from src.learner import get_knowledge_model

        get_knowledge_model().update_from_events(
            user_id, "Spanish", [{"skill": "grammar", "assessment": "incorrect", "confidence": 0.9}]
        )
        body = client.get("/api/v1/learner/cefr?language=Spanish", headers=headers).json()
        assert body["skills"]["grammar"]["cefr"] is None
        assert body["skills"]["grammar"]["status"] == "insufficient_evidence"
        assert body["overall"] is None


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
            assert s["status"] in ("insufficient_evidence", "provisional", "estimated")
            assert "coverage" in s


class TestExplainAndHistoryRoutes:
    def test_explain_lists_contributions(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        resp = client.get("/api/v1/learner/explain/vocabulary?language=Spanish", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["skill"] == "vocabulary"
        assert len(body["contributions"]) == 6
        assert all(c["role"] == "counted" for c in body["contributions"])
        assert body["estimate"]["method"] == "lkm-evidence-v2"

    def test_explain_unknown_skill_404(self, auth_client):
        client, headers, _ = auth_client
        resp = client.get("/api/v1/learner/explain/speaking?language=Spanish", headers=headers)
        assert resp.status_code == 404

    def test_history_traces_updates(self, auth_client):
        client, headers, user_id = auth_client
        _seed(user_id)
        resp = client.get("/api/v1/learner/history?language=Spanish", headers=headers)
        assert resp.status_code == 200
        updates = resp.json()["updates"]
        assert {u["skill"] for u in updates} == {"vocabulary", "grammar"}
        assert all(u["new_event_ids"] for u in updates)

    def test_audit_routes_require_auth(self, client):
        assert client.get("/api/v1/learner/history").status_code == 401
        assert client.get("/api/v1/learner/explain/grammar").status_code == 401

    def test_plan_actions_carry_intent(self, auth_client):
        client, headers, _ = auth_client
        body = client.get("/api/v1/learner/plan?language=Spanish", headers=headers).json()
        assert all(a["intent"] for a in body["actions"])
        assert "remediation" not in {a["intent"] for a in body["actions"]}


class TestInsightsRoute:
    def test_insights_new_learner(self, auth_client):
        client, headers, _ = auth_client
        body = client.get("/api/v1/learner/insights?language=Spanish", headers=headers).json()
        assert body["overall_cefr"] is None
        assert body["current_cefr"] is None  # no default working level logged
        assert body["weakest_skills"] == []  # nothing is called weak without evidence
        assert "grammar" in body["needs_assessment"]

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
