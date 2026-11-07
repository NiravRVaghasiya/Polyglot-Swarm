"""Shared API dependencies — authentication, budget scope, per-user limits."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api import auth
from src.config import settings
from src.observability import metrics
from src.observability.context import set_principal
from src.security.rate_limit import RateLimiter, RateLimitExceededError

_bearer = HTTPBearer(auto_error=False)

#: Per-user limiter for endpoints that do real work (LLM turns, assessment,
#: review submission). Shared by the whole process (ADR-0035).
user_work_limiter = RateLimiter(
    max_calls=max(1, settings.user_rate_limit_per_minute), window_seconds=60.0
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Resolve the authenticated ``user_id`` from a bearer token.

    Raises 401 if the token is missing or invalid. Async (with the lookup in
    a worker thread) so the principal it binds for LLM budgets is visible to
    the endpoint and everything it calls.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id: str | None = await run_in_threadpool(auth.resolve_token, credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    set_principal(user_id)
    return user_id


async def rate_limited_user(user_id: str = Depends(get_current_user)) -> str:
    """:func:`get_current_user` plus the per-user work rate limit (429)."""
    if settings.user_rate_limit_per_minute > 0:
        try:
            user_work_limiter.check(user_id)
        except RateLimitExceededError as exc:
            metrics.RATE_LIMITED.inc(scope="user_work")
            retry_after = max(1, int(exc.retry_after_seconds + 0.999))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "rate_limited", "message": "too many requests; slow down"},
                headers={"Retry-After": str(retry_after)},
            ) from exc
    return user_id
