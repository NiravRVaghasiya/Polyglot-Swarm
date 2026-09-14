"""Tests for API auth: register, login, token resolution, protected routes."""

from __future__ import annotations


class TestHealth:
    def test_health(self, client):
        assert client.get("/health").json() == {"status": "ok"}


class TestRegister:
    def test_register_returns_token(self, client):
        resp = client.post(
            "/api/v1/auth/register", json={"username": "bob", "password": "pw"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user_id"].startswith("u-")

    def test_duplicate_username_rejected(self, client):
        client.post("/api/v1/auth/register", json={"username": "dup", "password": "pw"})
        resp = client.post(
            "/api/v1/auth/register", json={"username": "dup", "password": "pw"}
        )
        assert resp.status_code == 400

    def test_creates_profile(self, client):
        resp = client.post(
            "/api/v1/auth/register", json={"username": "carol", "password": "pw"}
        )
        user_id = resp.json()["user_id"]
        from src.memory.user_profile import profile_exists

        assert profile_exists(user_id)


class TestLogin:
    def test_login_success(self, client):
        client.post("/api/v1/auth/register", json={"username": "dave", "password": "pw"})
        resp = client.post(
            "/api/v1/auth/login", json={"username": "dave", "password": "pw"}
        )
        assert resp.status_code == 200
        assert resp.json()["access_token"]

    def test_wrong_password_rejected(self, client):
        client.post("/api/v1/auth/register", json={"username": "eve", "password": "pw"})
        resp = client.post(
            "/api/v1/auth/login", json={"username": "eve", "password": "wrong"}
        )
        assert resp.status_code == 401

    def test_unknown_user_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/login", json={"username": "ghost", "password": "pw"}
        )
        assert resp.status_code == 401


class TestProtectedRoutes:
    def test_me_requires_auth(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_me_rejects_bad_token(self, client):
        resp = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer nope"}
        )
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
