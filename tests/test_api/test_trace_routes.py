"""Phase 17 tests: the trace API route (GET /api/v1/trace/{session_id})."""

from __future__ import annotations


class TestTraceRoute:
    def test_requires_auth(self, client):
        assert client.get("/api/v1/trace/some-session").status_code == 401

    def test_empty_session_returns_empty_trace(self, auth_client):
        client, headers, user_id = auth_client
        resp = client.get("/api/v1/trace/does-not-exist", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == "does-not-exist"
        assert body["user_id"] == user_id
        assert body["spans"] == []
        assert body["interactions"] == []

    def test_full_turn_produces_a_correlated_trace(self, auth_client):
        # Drive one real turn through the API (deterministic FakeProvider,
        # no per-agent mocking) so model_runs + evidence are both populated
        # and correlated by the same interaction id end-to-end.
        client, headers, user_id = auth_client
        from src.memory import model_runs

        model_runs.enable_persistence()

        start = client.post("/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers)
        assert start.status_code == 200
        session_id = start.json()["session_id"]

        chat = client.post(
            "/api/v1/chat",
            json={"session_id": session_id, "message": "Hola, quiero una mesa"},
            headers=headers,
        )
        assert chat.status_code == 200

        resp = client.get(f"/api/v1/trace/{session_id}", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        assert body["interactions"], "expected at least one correlated interaction"

        kinds = {s["kind"] for s in body["spans"]}
        assert "model_run" in kinds  # conversation/grammar/vocabulary/cultural all call the LLM
        for span in body["spans"]:
            assert span["timestamp"]
            assert span["summary"]

    def test_trace_isolated_between_users(self, client):
        # User A's session trace must not be visible to user B, even for the
        # same session id (guards the model_runs join, which has no user
        # column of its own).
        a = client.post("/api/v1/auth/register", json={"username": "trace-a", "password": "pw"})
        b = client.post("/api/v1/auth/register", json={"username": "trace-b", "password": "pw"})
        ha = {"Authorization": f"Bearer {a.json()['access_token']}"}
        hb = {"Authorization": f"Bearer {b.json()['access_token']}"}

        sid = client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=ha
        ).json()["session_id"]

        resp_b = client.get(f"/api/v1/trace/{sid}", headers=hb)
        assert resp_b.status_code == 200
        assert resp_b.json()["spans"] == []
