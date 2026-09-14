"""Authentication store — users and bearer tokens (SQLite, bcrypt).

Multi-user auth for the API. Passwords are hashed with bcrypt; sessions use
opaque bearer tokens persisted in SQLite (simple, dependency-light, and
adequate for the local-first deployment). The ``user_id`` resolved from a token
is what flows into the memory layer, so every user's data stays isolated.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import bcrypt

from src.memory.db import get_connection

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
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""


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


def register(username: str, password: str) -> str:
    """Register a new user; returns the new ``user_id``.

    Raises :class:`AuthError` if the username is taken or inputs are invalid.
    """
    if not username or not password:
        raise AuthError("username and password are required")

    init_db()
    user_id = f"u-{uuid.uuid4().hex[:12]}"
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise AuthError("username already taken")
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, username, _hash_password(password), _now()),
        )
    return user_id


def login(username: str, password: str) -> str:
    """Verify credentials and return a new bearer token.

    Raises :class:`AuthError` on invalid credentials.
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
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, row["user_id"], _now()),
        )
    return token


def resolve_token(token: str) -> str | None:
    """Return the ``user_id`` for a valid token, or None if unknown."""
    if not token:
        return None
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id FROM auth_tokens WHERE token = ?", (token,)
        ).fetchone()
    return row["user_id"] if row else None


def logout(token: str) -> None:
    """Invalidate a bearer token."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
