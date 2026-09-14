"""Tests for review, progress, scenarios, and profile routes."""

from __future__ import annotations


class TestScenarios:
    def test_requires_auth(self, client):
        assert client.get("/api/v1/scenarios").status_code == 401

    def test_lists_all(self, auth_client):
        client, headers, _ = auth_client
        resp = client.get("/api/v1/scenarios", headers=headers)
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["scenarios"]]
        assert "es_restaurant_ordering" in ids
        assert len(ids) == 15

    def test_filter_by_language(self, auth_client):
        client, headers, _ = auth_client
        resp = client.get("/api/v1/scenarios?language=it", headers=headers)
        scenarios = resp.json()["scenarios"]
        assert all(s["language"] == "it" for s in scenarios)
        assert len(scenarios) == 5


class TestProfile:
    def test_get_default_profile(self, auth_client):
        client, headers, user_id = auth_client
        resp = client.get("/api/v1/profile", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["user_id"] == user_id

    def test_update_profile(self, auth_client):
        client, headers, _ = auth_client
        resp = client.put(
            "/api/v1/profile",
            json={"interests": ["cooking", "travel"], "goals": ["fluency"]},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["interests"] == ["cooking", "travel"]

        # Persisted across requests.
        again = client.get("/api/v1/profile", headers=headers)
        assert again.json()["goals"] == ["fluency"]

    def test_partial_update_keeps_other_fields(self, auth_client):
        client, headers, _ = auth_client
        client.put("/api/v1/profile", json={"native_language": "Polish"}, headers=headers)
        client.put("/api/v1/profile", json={"interests": ["music"]}, headers=headers)
        resp = client.get("/api/v1/profile", headers=headers)
        body = resp.json()
        assert body["native_language"] == "Polish"
        assert body["interests"] == ["music"]


class TestReview:
    def test_due_empty_for_new_user(self, auth_client):
        client, headers, _ = auth_client
        resp = client.get("/api/v1/review/due?language=Spanish", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["due"] == []

    def test_due_reflects_scheduled(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word(
            user_id, "Spanish", "mesa", next_review="2020-01-01T00:00:00+00:00"
        )
        resp = client.get("/api/v1/review/due?language=Spanish", headers=headers)
        words = [d["word"] for d in resp.json()["due"]]
        assert "mesa" in words

    def test_submit_records_outcome(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word(user_id, "Spanish", "mesa")
        resp = client.post(
            "/api/v1/review/submit?language=Spanish",
            json={"word": "mesa", "correct": True},
            headers=headers,
        )
        assert resp.status_code == 200
        row = vocabulary_db.get_all_for_user(user_id, "Spanish")[0]
        assert row["times_correct"] == 1


class TestProgress:
    def test_overview(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import analytics

        analytics.log_session(user_id, "Spanish", new_words_learned=3,
                              cefr_estimate="A2")
        resp = client.get("/api/v1/progress/overview?language=Spanish", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_sessions"] == 1
        assert body["current_cefr"] == "A2"

    def test_weaknesses(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import analytics

        for _ in range(2):
            analytics.record_error(user_id, "Spanish", "ser_vs_estar")
        resp = client.get("/api/v1/progress/weaknesses?language=Spanish", headers=headers)
        weaknesses = resp.json()["weaknesses"]
        assert weaknesses[0]["error_type"] == "ser_vs_estar"

    def test_progress_requires_auth(self, client):
        assert client.get("/api/v1/progress/overview").status_code == 401
