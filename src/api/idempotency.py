"""Idempotency keys for mutating learning endpoints (ADR-0035, R13).

A client that retries a request after a timeout (mobile networks, a
double-tapped button) must not record the same review or assessment twice.
Endpoints that record learning events accept an optional ``Idempotency-Key``
header:

- **First request with a key:** the key is claimed, the work runs, and the
  JSON response is stored.
- **Same key again, same body:** the stored response is replayed and nothing
  is recorded twice.
- **Same key again while the first is still running:** ``409``.
- **Same key with a different body:** ``422``, because the key was reused.

If the work fails, the claim is released, so the client can retry with the
same key. Keys are scoped per user and kept for
:data:`RETENTION_HOURS` (maintenance prunes them).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Header, HTTPException, status

RETENTION_HOURS = 24
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def idempotency_key(
    key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    """FastAPI dependency: the validated ``Idempotency-Key`` header, if any."""
    if key is None:
        return None
    if not _KEY.match(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be 8-128 characters of A-Z a-z 0-9 _ -",
        )
    return key


def _conn() -> Any:
    from src.memory.db import get_connection

    return get_connection()


@dataclass
class Claim:
    user_id: str
    key: str | None
    endpoint: str
    replayed: dict[str, Any] | None = None

    def complete(self, response: dict[str, Any], status_code: int = 200) -> dict[str, Any]:
        if self.key is not None:
            with _conn() as conn:
                conn.execute(
                    "UPDATE idempotency_keys SET status_code = ?, response_json = ? "
                    "WHERE user_id = ? AND key = ?",
                    (status_code, json.dumps(response, default=str), self.user_id, self.key),
                )
        return response

    def abandon(self) -> None:
        if self.key is not None:
            with _conn() as conn:
                conn.execute(
                    "DELETE FROM idempotency_keys WHERE user_id = ? AND key = ? "
                    "AND status_code IS NULL",
                    (self.user_id, self.key),
                )


def begin(user_id: str, key: str | None, endpoint: str, body: Any) -> Claim:
    """Claim ``key`` for this request, or return the stored response to replay."""
    if key is None:
        return Claim(user_id, None, endpoint)
    request_hash = hashlib.sha256(
        json.dumps([endpoint, body], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    with _conn() as conn:
        inserted = conn.execute(
            "INSERT OR IGNORE INTO idempotency_keys "
            "(user_id, key, endpoint, request_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, key, endpoint, request_hash, datetime.now(UTC).isoformat()),
        ).rowcount
        if inserted:
            return Claim(user_id, key, endpoint)
        row = conn.execute(
            "SELECT request_hash, status_code, response_json FROM idempotency_keys "
            "WHERE user_id = ? AND key = ?",
            (user_id, key),
        ).fetchone()
    if row["request_hash"] != request_hash:
        raise HTTPException(
            status_code=422,
            detail={"code": "idempotency_key_reused", "message": "key used for another request"},
        )
    if row["status_code"] is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "in_progress", "message": "the original request is still running"},
        )
    return Claim(user_id, key, endpoint, replayed=json.loads(row["response_json"]))


def prune(*, hours: int = RETENTION_HOURS) -> int:
    """Delete keys older than ``hours`` (maintenance)."""
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    with _conn() as conn:
        return int(
            conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (cutoff,)).rowcount
        )
