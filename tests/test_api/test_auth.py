"""Tests for API auth: register, login, token resolution, protected routes."""

from __future__ import annotations


class TestHealth:
    def test_health(self, client):
        from src import __version__

        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["version"] == __version__


class TestReadiness:
    """Phase 23: /ready checks DB/provider/vector-store, distinct from the
    liveness-only /health above."""

    def test_ready_ok_when_everything_healthy(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["checks"]["database"]["ok"] is True
        assert body["checks"]["llm_providers"]["ok"] is True
        assert body["checks"]["vector_store"]["ok"] is True

    def test_ready_reports_llm_provider_chain_details(self, client):
        body = client.get("/ready").json()
        tiers = body["checks"]["llm_providers"]["tiers"]
        assert set(tiers) == {"primary", "fast", "local"}
        for health in tiers.values():
            assert health["available"] is True  # deterministic fake provider

    def test_ready_returns_503_when_database_unreachable(self, client, monkeypatch):
        from src.api import app as app_module

        monkeypatch.setattr(
            app_module,
            "_check_database",
            lambda: {"ok": False, "error": "boom"},
        )

        resp = client.get("/ready")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unavailable"
        assert body["checks"]["database"]["ok"] is False

    def test_ready_returns_503_when_no_llm_provider_available(self, client, monkeypatch):
        from src.api import app as app_module

        monkeypatch.setattr(
            app_module,
            "_check_llm_providers",
            lambda: {"ok": False, "tiers": {}},
        )

        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unavailable"

    def test_ready_stays_ok_when_vector_store_degraded(self, client, monkeypatch):
        # Vector store is enrichment, not core — a failure there degrades but
        # does not flip overall readiness to unavailable.
        from src.api import app as app_module

        monkeypatch.setattr(
            app_module,
            "_check_vector_store",
            lambda: {"ok": True, "degraded": True, "error": "chroma down"},
        )

        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["checks"]["vector_store"]["degraded"] is True


class TestRegister:
    def test_register_returns_token(self, client):
        resp = client.post("/api/v1/auth/register", json={"username": "bob", "password": "pw"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user_id"].startswith("u-")

    def test_duplicate_username_rejected(self, client):
        client.post("/api/v1/auth/register", json={"username": "dup", "password": "pw"})
        resp = client.post("/api/v1/auth/register", json={"username": "dup", "password": "pw"})
        assert resp.status_code == 400

    def test_creates_profile(self, client):
        resp = client.post("/api/v1/auth/register", json={"username": "carol", "password": "pw"})
        user_id = resp.json()["user_id"]
        from src.memory.user_profile import profile_exists

        assert profile_exists(user_id)


class TestLogin:
    def test_login_success(self, client):
        client.post("/api/v1/auth/register", json={"username": "dave", "password": "pw"})
        resp = client.post("/api/v1/auth/login", json={"username": "dave", "password": "pw"})
        assert resp.status_code == 200
        assert resp.json()["access_token"]

    def test_wrong_password_rejected(self, client):
        client.post("/api/v1/auth/register", json={"username": "eve", "password": "pw"})
        resp = client.post("/api/v1/auth/login", json={"username": "eve", "password": "wrong"})
        assert resp.status_code == 401

    def test_unknown_user_rejected(self, client):
        resp = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "pw"})
        assert resp.status_code == 401


class TestProtectedRoutes:
    def test_me_requires_auth(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_rejects_bad_token(self, client):
        resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_me_resolves_user(self, auth_client):
        client, headers, user_id = auth_client
        resp = client.get("/api/v1/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["user_id"] == user_id
        assert resp.json()["username"] == "alice"

    def test_two_users_isolated(self, client):
        r1 = client.post("/api/v1/auth/register", json={"username": "u_a", "password": "pw"})
        r2 = client.post("/api/v1/auth/register", json={"username": "u_b", "password": "pw"})
        assert r1.json()["user_id"] != r2.json()["user_id"]
