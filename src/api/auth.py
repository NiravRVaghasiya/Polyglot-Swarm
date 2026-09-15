"""Authentication store — users and bearer tokens (SQLite, bcrypt).

Multi-user auth for the API. Passwords are hashed with bcrypt; sessions use
opaque bearer tokens (simple, dependency-light, and adequate for the
local-first deployment). The ``user_id`` resolved from a token is what flows
into the memory layer, so every user's data stays isolated.

Phase 21 hardening, on top of the original design:

- **Tokens are hashed at rest.** The ``auth_tokens.token`` column stores a
  SHA-256 hash of the bearer token, not the raw value — if the database file
  ever leaked, stored tokens would not be directly replayable (mirrors how
  passwords are never stored raw either). The raw token is returned to the
  caller once, at login/registration time, exactly as before; only its hash
  is persisted.
- **Tokens expire.** Each token carries an ``expires_at`` (see migration
  0006); :func:`resolve_token` treats an expired token as invalid and opens
  the ``login``/``register`` contract to :data:`src.config.settings.
  token_ttl_hours` for how long a session lasts.
- **Rate limiting** on login/registration is provided as a reusable
  :class:`~src.security.rate_limit.RateLimiter`
  (:data:`login_rate_limiter`/:data:`register_rate_limiter`) that
  ``src.api.routes.auth_routes`` checks before attempting the operation —
  kept here as the shared instances so the whole process shares one set of
  counters.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt

from src.config import settings
from src.memory.db import get_connection
from src.security.rate_limit import RateLimiter

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""

#: Shared rate limiters for the auth endpoints (Phase 21). Keyed by whatever
#: the caller (the API layer) chooses — typically the client IP, or a
#: composite of IP + username to also blunt spraying one account from many
#: IPs. Deliberately generous defaults for a local-first, mostly-single-user
#: product; tune via direct attribute access if self-hosting for a group.
login_rate_limiter = RateLimiter(max_calls=10, window_seconds=60.0)
register_rate_limiter = RateLimiter(max_calls=5, window_seconds=60.0)


class AuthError(Exception):
    """Raised for registration/login failures."""


def init_db() -> None:
    """Create the users and auth_tokens tables if they do not exist."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _hash_token(token: str) -> str:
    """SHA-256 the raw bearer token for storage.

    SHA-256 (not bcrypt) is appropriate here: the token is already a
    cryptographically random 256-bit value (``secrets.token_urlsafe(32)``),
    not a low-entropy human-chosen secret, so it needs no salting or slow
    hashing to resist brute force — a fast, deterministic hash is exactly
    what a lookup-by-hash needs.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register(username: str, password: str) -> str:
    """Register a new user; returns the new ``user_id``.

    Raises :class:`AuthError` if the username is taken or inputs are invalid.
    """
    if not username or not password:
        raise AuthError("username and password are required")

    init_db()
    user_id = f"u-{uuid.uuid4().hex[:12]}"
    with get_connection() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            raise AuthError("username already taken")
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, _hash_password(password), _now()),
        )
    return user_id


def login(username: str, password: str) -> str:
    """Verify credentials and return a new bearer token.

    The returned token is the raw, unhashed value — this is the only place it
    ever exists outside the caller's possession; only its SHA-256 hash is
    persisted. Raises :class:`AuthError` on invalid credentials.
    """
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not _verify_password(password, row["password_hash"]):
            raise AuthError("invalid username or password")

        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + timedelta(hours=settings.token_ttl_hours)
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_hash_token(token), row["user_id"], now.isoformat(), expires_at.isoformat()),
        )
    return token


def resolve_token(token: str) -> str | None:
    """Return the ``user_id`` for a valid, non-expired token, or ``None``.

    An expired token resolves to ``None`` exactly like an unknown one — the
    caller (typically :func:`src.api.deps.get_current_user`) cannot
    distinguish "never existed" from "expired", which is the conservative,
    information-non-leaking choice.
    """
    if not token:
        return None
    init_db()
    token_hash = _hash_token(token)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id, expires_at FROM auth_tokens WHERE token = ?", (token_hash,)
        ).fetchone()
    if row is None:
        return None
    expires_at = row["expires_at"]
    if expires_at is not None and datetime.fromisoformat(expires_at) <= datetime.now(UTC):
        return None
    return str(row["user_id"])


def logout(token: str) -> None:
    """Invalidate a bearer token."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (_hash_token(token),))


def delete_tokens_for_user(user_id: str) -> int:
    """Delete every bearer token for ``user_id`` (Phase 21 data deletion).

    Used when erasing a user's account/data — after this, no previously
    issued token for them resolves. Distinct from :func:`logout` (which
    invalidates one specific token) and :func:`purge_expired_tokens` (which
    is time-based housekeeping, not user-scoped).
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
        return cursor.rowcount


def delete_user(user_id: str) -> bool:
    """Delete the account row itself (Phase 21 data deletion).

    Does not cascade to tokens or any memory-layer data — callers (
    :mod:`src.memory.privacy`) are responsible for deleting those first,
    since ``users`` has no ``ON DELETE CASCADE`` (SQLite foreign keys here are
    declarative, not enforced by default) and deletion order matters for a
    clean, complete erasure. Returns whether a row was removed.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0


def purge_expired_tokens() -> int:
    """Delete every expired token. Returns the number of rows removed.

    Not called automatically on every request (that would be wasteful); a
    caller (a scheduled task, or the CLI/admin surface) runs this
    periodically. Expired tokens are already treated as invalid by
    :func:`resolve_token` regardless of whether this has run — this is
    housekeeping, not a security boundary.
    """
    init_db()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM auth_tokens WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (datetime.now(UTC).isoformat(),),
        )
        return cursor.rowcount
