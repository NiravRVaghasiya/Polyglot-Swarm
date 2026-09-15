"""Tests for session and chat routes."""

from __future__ import annotations


class TestStartSession:
    def test_requires_auth(self, client):
        assert client.post("/api/v1/sessions/start", json={}).status_code == 401

    def test_start_free_conversation(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post("/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"]
        assert body["language"] == "Spanish"

    def test_start_with_scenario(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post(
            "/api/v1/sessions/start",
            json={"scenario_id": "es_restaurant_ordering"},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["language"] == "Spanish"
        assert "Madrileña" in body["opening_line"]

    def test_unknown_scenario_404(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post(
            "/api/v1/sessions/start",
            json={"scenario_id": "does_not_exist"},
            headers=headers,
        )
        assert resp.status_code == 404


class TestChat:
    def _start(self, client, headers):
        return client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
        ).json()["session_id"]

    def test_chat_returns_reply_and_feedback(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        sid = self._start(client, headers)
        resp = client.post(
            "/api/v1/chat",
            json={"session_id": sid, "message": "Hola, una mesa por favor"},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["reply"]
        assert "grammar" in body["hidden_feedback"]
        assert "vocabulary" in body["hidden_feedback"]
        assert "cultural" in body["hidden_feedback"]

    def test_chat_unknown_session_404(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        resp = client.post(
            "/api/v1/chat",
            json={"session_id": "nope", "message": "hi"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_chat_requires_auth(self, client):
        resp = client.post("/api/v1/chat", json={"session_id": "x", "message": "hi"})
        assert resp.status_code == 401

    def test_session_isolated_between_users(self, client, mock_llm):
        # User A starts a session; user B cannot access it.
        a = client.post("/api/v1/auth/register", json={"username": "aa", "password": "pw"}).json()
        b = client.post("/api/v1/auth/register", json={"username": "bb", "password": "pw"}).json()
        ha = {"Authorization": f"Bearer {a['access_token']}"}
        hb = {"Authorization": f"Bearer {b['access_token']}"}

        sid = client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=ha
        ).json()["session_id"]

        resp = client.get(f"/api/v1/sessions/{sid}/state", headers=hb)
        assert resp.status_code == 404


class TestSessionState:
    def test_turn_count_increments(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        sid = client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
        ).json()["session_id"]

        client.post(
            "/api/v1/chat",
            json={"session_id": sid, "message": "Hola"},
            headers=headers,
        )
        resp = client.get(f"/api/v1/sessions/{sid}/state", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["turn_count"] >= 1


class TestEndSession:
    def test_end_returns_report(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        sid = client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
        ).json()["session_id"]
        client.post(
            "/api/v1/chat",
            json={"session_id": sid, "message": "Hola una mesa"},
            headers=headers,
        )
        resp = client.post(f"/api/v1/sessions/{sid}/end", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "Session Report" in body["report"]
        assert "vocabulary" in body["persisted"]
        # Session removed after ending.
        assert client.get(f"/api/v1/sessions/{sid}/state", headers=headers).status_code == 404
