"""Phase 21 tests: token expiry, hashing at rest, and rate limiting — unit
tests against src.api.auth directly (below the HTTP layer tested in
test_auth.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.api import auth
from src.config import settings
from src.memory.db import get_connection
from src.security.rate_limit import RateLimitExceededError


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Every test gets a clean rate-limit budget (these are process-global)."""
    auth.login_rate_limiter.reset()
    auth.register_rate_limiter.reset()
    yield
    auth.login_rate_limiter.reset()
    auth.register_rate_limiter.reset()


class TestTokenHashedAtRest:
    def test_raw_token_is_not_stored(self, temp_storage):
        auth.register("hashtest", "pw-secret-1")
        token = auth.login("hashtest", "pw-secret-1")
        with get_connection() as conn:
            row = conn.execute("SELECT token FROM auth_tokens").fetchone()
        assert row["token"] != token

    def test_stored_value_is_the_sha256_hash(self, temp_storage):
        auth.register("hashtest2", "pw-secret-1")
        token = auth.login("hashtest2", "pw-secret-1")
        with get_connection() as conn:
            row = conn.execute("SELECT token FROM auth_tokens").fetchone()
        assert row["token"] == auth._hash_token(token)

    def test_resolve_token_still_works_with_the_raw_token(self, temp_storage):
        user_id = auth.register("hashtest3", "pw-secret-1")
        token = auth.login("hashtest3", "pw-secret-1")
        assert auth.resolve_token(token) == user_id

    def test_wrong_raw_token_does_not_resolve(self, temp_storage):
        auth.register("hashtest4", "pw-secret-1")
        auth.login("hashtest4", "pw-secret-1")
        assert auth.resolve_token("some-other-token-entirely") is None


class TestTokenExpiry:
    def test_fresh_token_has_a_future_expiry(self, temp_storage):
        auth.register("expirytest", "pw-secret-1")
        token = auth.login("expirytest", "pw-secret-1")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT expires_at FROM auth_tokens WHERE token = ?",
                (auth._hash_token(token),),
            ).fetchone()
        expires_at = datetime.fromisoformat(row["expires_at"])
        assert expires_at > datetime.now(UTC)

    def test_expired_token_does_not_resolve(self, temp_storage, monkeypatch):
        user_id = auth.register("expirytest2", "pw-secret-1")
        token = auth.login("expirytest2", "pw-secret-1")
        assert auth.resolve_token(token) == user_id

        # Force the stored expiry into the past.
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        with get_connection() as conn:
            conn.execute(
                "UPDATE auth_tokens SET expires_at = ? WHERE token = ?",
                (past, auth._hash_token(token)),
            )

        assert auth.resolve_token(token) is None

    def test_token_ttl_setting_controls_expiry_window(self, temp_storage, monkeypatch):
        monkeypatch.setattr(settings, "token_ttl_hours", 1, raising=False)
        auth.register("expirytest3", "pw-secret-1")
        token = auth.login("expirytest3", "pw-secret-1")
        with get_connection() as conn:
            row = conn.execute(
                "SELECT created_at, expires_at FROM auth_tokens WHERE token = ?",
                (auth._hash_token(token),),
            ).fetchone()
        created = datetime.fromisoformat(row["created_at"])
        expires = datetime.fromisoformat(row["expires_at"])
        assert abs((expires - created) - timedelta(hours=1)) < timedelta(seconds=5)


class TestPurgeExpiredTokens:
    def test_removes_only_expired_tokens(self, temp_storage):
        auth.register("purgetest", "pw-secret-1")
        live_token = auth.login("purgetest", "pw-secret-1")
        expired_token = auth.login("purgetest", "pw-secret-1")

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        with get_connection() as conn:
            conn.execute(
                "UPDATE auth_tokens SET expires_at = ? WHERE token = ?",
                (past, auth._hash_token(expired_token)),
            )

        removed = auth.purge_expired_tokens()
        assert removed == 1
        assert auth.resolve_token(live_token) is not None
        assert auth.resolve_token(expired_token) is None

    def test_no_expired_tokens_removes_nothing(self, temp_storage):
        auth.register("purgetest2", "pw-secret-1")
        auth.login("purgetest2", "pw-secret-1")
        assert auth.purge_expired_tokens() == 0


class TestDeleteTokensForUser:
    def test_removes_every_token_for_the_user(self, temp_storage):
        user_id = auth.register("multitoken", "pw-secret-1")
        t1 = auth.login("multitoken", "pw-secret-1")
        t2 = auth.login("multitoken", "pw-secret-1")
        assert auth.resolve_token(t1) == user_id
        assert auth.resolve_token(t2) == user_id

        removed = auth.delete_tokens_for_user(user_id)

        assert removed == 2
        assert auth.resolve_token(t1) is None
        assert auth.resolve_token(t2) is None

    def test_does_not_affect_other_users_tokens(self, temp_storage):
        u1 = auth.register("victim", "pw-secret-1")
        auth.register("bystander", "pw-secret-1")
        t1 = auth.login("victim", "pw-secret-1")
        t2 = auth.login("bystander", "pw-secret-1")

        auth.delete_tokens_for_user(u1)

        assert auth.resolve_token(t1) is None
        assert auth.resolve_token(t2) is not None


class TestDeleteUser:
    def test_removes_the_account_row(self, temp_storage):
        user_id = auth.register("deleteacct", "pw-secret-1")
        assert auth.delete_user(user_id) is True
        with pytest.raises(auth.AuthError):
            auth.login("deleteacct", "pw-secret-1")

    def test_unknown_user_returns_false(self, temp_storage):
        assert auth.delete_user("no-such-user") is False


class TestRateLimiters:
    def test_login_rate_limiter_blocks_after_max_calls(self, temp_storage):
        auth.register("ratelimited", "pw-secret-1")
        for _ in range(auth.login_rate_limiter.max_calls):
            auth.login_rate_limiter.check("1.2.3.4")
        with pytest.raises(RateLimitExceededError):
            auth.login_rate_limiter.check("1.2.3.4")

    def test_register_rate_limiter_blocks_after_max_calls(self, temp_storage):
        for _ in range(auth.register_rate_limiter.max_calls):
            auth.register_rate_limiter.check("1.2.3.4")
        with pytest.raises(RateLimitExceededError):
            auth.register_rate_limiter.check("1.2.3.4")

    def test_rate_limiters_are_keyed_independently_per_client(self, temp_storage):
        for _ in range(auth.login_rate_limiter.max_calls):
            auth.login_rate_limiter.check("client-a")
        auth.login_rate_limiter.check("client-b")  # different key, must not raise
