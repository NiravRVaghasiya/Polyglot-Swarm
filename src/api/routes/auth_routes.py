"""Authentication routes: register, login, current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api import auth
from src.api.deps import get_current_user
from src.api.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from src.memory import user_profile
from src.security.audit import log_event
from src.security.rate_limit import RateLimitExceededError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    """A best-effort per-client rate-limit key.

    Falls back to a constant when no client host is available (e.g. some test
    clients) — this degrades to one shared bucket rather than raising, which
    is the safe direction for a rate limiter's own plumbing to fail in.
    """
    client = request.client
    return client.host if client else "unknown"


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, request: Request) -> TokenResponse:
    """Register a new user and return a bearer token."""
    try:
        auth.register_rate_limiter.check(_client_key(request))
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    try:
        user_id = auth.register(req.username, req.password)
    except auth.AuthError as exc:
        log_event("register_failed", detail={"username": req.username, "reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Create a default profile for the new user.
    user_profile.create_profile(user_id)
    token = auth.login(req.username, req.password)
    log_event("register", user_id=user_id, detail={"username": req.username})
    return TokenResponse(access_token=token, user_id=user_id)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request) -> TokenResponse:
    """Authenticate and return a bearer token."""
    try:
        auth.login_rate_limiter.check(_client_key(request))
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    try:
        token = auth.login(req.username, req.password)
    except auth.AuthError as exc:
        log_event("login_failed", detail={"username": req.username})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user_id = auth.resolve_token(token)
    assert user_id is not None
    log_event("login", user_id=user_id, detail={"username": req.username})
    return TokenResponse(access_token=token, user_id=user_id)


@router.get("/me", response_model=UserResponse)
def me(user_id: str = Depends(get_current_user)) -> UserResponse:
    """Return the current authenticated user."""
    from src.memory.db import get_connection

    with get_connection() as conn:
        row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
    username = row["username"] if row else ""
    return UserResponse(user_id=user_id, username=username)
