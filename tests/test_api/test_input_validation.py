"""Bad input gets a clear 400 instead of a crash or a wasted LLM turn."""

from __future__ import annotations


class TestRegistration:
    def test_password_over_bcrypt_limit_is_rejected_not_500(self, client):
        resp = client.post(
            "/api/v1/auth/register", json={"username": "longpw", "password": "x" * 80}
        )
        assert resp.status_code == 400
        assert "72" in resp.json()["detail"]

    def test_multibyte_password_limit_counts_bytes(self, client):
        # 30 three-byte characters are 90 bytes, over bcrypt's 72-byte input.
        resp = client.post(
            "/api/v1/auth/register", json={"username": "kanji", "password": "語" * 30}
        )
        assert resp.status_code == 400

    def test_blank_username_is_rejected(self, client):
        resp = client.post("/api/v1/auth/register", json={"username": "   ", "password": "pw"})
        assert resp.status_code == 400

    def test_username_is_trimmed_for_register_and_login(self, client):
        resp = client.post("/api/v1/auth/register", json={"username": " bob ", "password": "pw1"})
        assert resp.status_code == 200
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "bob", "password": "pw1"}
            ).status_code
            == 200
        )
        # The trimmed name is taken, so a padded duplicate is refused too.
        assert (
            client.post(
                "/api/v1/auth/register", json={"username": "bob  ", "password": "pw2"}
            ).status_code
            == 400
        )


class TestChatMessage:
    def _session(self, client, headers):
        return client.post(
            "/api/v1/sessions/start", json={"language": "Spanish"}, headers=headers
        ).json()["session_id"]

    def test_blank_message_is_rejected(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        sid = self._session(client, headers)
        resp = client.post(
            "/api/v1/chat", json={"session_id": sid, "message": "  "}, headers=headers
        )
        assert resp.status_code == 400
        assert isinstance(resp.json()["detail"], str)

    def test_overlong_message_is_rejected(self, auth_client, mock_llm):
        client, headers, _ = auth_client
        sid = self._session(client, headers)
        resp = client.post(
            "/api/v1/chat", json={"session_id": sid, "message": "a" * 5000}, headers=headers
        )
        assert resp.status_code == 400
