"""Phase 21 tests: self-service data export/deletion routes and rate limiting."""

from __future__ import annotations


class TestPrivacyRoutes:
    def test_export_requires_auth(self, client):
        assert client.get("/api/v1/privacy/export").status_code == 401

    def test_delete_requires_auth(self, client):
        assert client.delete("/api/v1/privacy/data").status_code == 401

    def test_export_returns_the_users_own_account(self, auth_client):
        client, headers, user_id = auth_client
        resp = client.get("/api/v1/privacy/export", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["account"]["user_id"] == user_id

    def test_export_includes_seeded_vocabulary(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word(user_id, "Spanish", "mesa")
        resp = client.get("/api/v1/privacy/export", headers=headers)
        words = [v["word"] for v in resp.json()["data"]["vocabulary"]]
        assert "mesa" in words

    def test_delete_removes_data_and_invalidates_the_session(self, auth_client):
        client, headers, user_id = auth_client
        resp = client.delete("/api/v1/privacy/data", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["deleted"]["account"] is True

        # The token used to make the delete request no longer resolves.
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 401

    def test_delete_does_not_affect_other_users(self, client):
        a = client.post(
            "/api/v1/auth/register", json={"username": "priv-a", "password": "pw-secret-1"}
        )
        b = client.post(
            "/api/v1/auth/register", json={"username": "priv-b", "password": "pw-secret-1"}
        )
        ha = {"Authorization": f"Bearer {a.json()['access_token']}"}
        hb = {"Authorization": f"Bearer {b.json()['access_token']}"}

        client.delete("/api/v1/privacy/data", headers=ha)

        # User B's session is untouched.
        assert client.get("/api/v1/auth/me", headers=hb).status_code == 200


class TestAuthRateLimiting:
    def test_login_returns_429_after_exceeding_the_limit(self, client):
        client.post("/api/v1/auth/register", json={"username": "burst", "password": "pw-secret-1"})
        from src.api import auth

        limit = auth.login_rate_limiter.max_calls
        for _ in range(limit):
            client.post("/api/v1/auth/login", json={"username": "burst", "password": "pw-secret-1"})
        resp = client.post(
            "/api/v1/auth/login", json={"username": "burst", "password": "pw-secret-1"}
        )
        assert resp.status_code == 429

    def test_register_returns_429_after_exceeding_the_limit(self, client):
        from src.api import auth

        limit = auth.register_rate_limiter.max_calls
        for i in range(limit):
            client.post(
                "/api/v1/auth/register", json={"username": f"spam{i}", "password": "pw-secret-1"}
            )
        resp = client.post(
            "/api/v1/auth/register", json={"username": "one-too-many", "password": "pw-secret-1"}
        )
        assert resp.status_code == 429

    def test_login_is_limited_per_account_whatever_the_client_ip(self, client):
        """Behind a proxy the IP comes from a header, so guessing must also be
        capped per account."""
        client.post("/api/v1/auth/register", json={"username": "victim", "password": "pw-secret-1"})
        from src.api import auth

        for _ in range(auth.login_rate_limiter.max_calls):
            auth.login_rate_limiter.reset("testclient")  # a fresh (spoofed) IP each try
            client.post("/api/v1/auth/login", json={"username": "victim", "password": "wrong-pw"})
        auth.login_rate_limiter.reset("testclient")
        resp = client.post(
            "/api/v1/auth/login", json={"username": "Victim ", "password": "pw-secret-1"}
        )
        assert resp.status_code == 429
        # Other accounts are unaffected.
        client.post("/api/v1/auth/register", json={"username": "other", "password": "pw-secret-1"})
        resp = client.post(
            "/api/v1/auth/login", json={"username": "other", "password": "pw-secret-1"}
        )
        assert resp.status_code == 200
