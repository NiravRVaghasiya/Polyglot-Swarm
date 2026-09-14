"""Authentication routes: register, login, current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.api import auth
from src.api.deps import get_current_user
from src.api.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from src.memory import user_profile

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest) -> TokenResponse:
    """Register a new user and return a bearer token."""
    try:
        user_id = auth.register(req.username, req.password)
    except auth.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Create a default profile for the new user.
    user_profile.create_profile(user_id)
    token = auth.login(req.username, req.password)
    return TokenResponse(access_token=token, user_id=user_id)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest) -> TokenResponse:
    """Authenticate and return a bearer token."""
    try:
        token = auth.login(req.username, req.password)
    except auth.AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    user_id = auth.resolve_token(token)
    assert user_id is not None
    return TokenResponse(access_token=token, user_id=user_id)


@router.get("/me", response_model=UserResponse)
def me(user_id: str = Depends(get_current_user)) -> UserResponse:
    """Return the current authenticated user."""
    from src.memory.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT username FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    username = row["username"] if row else ""
    return UserResponse(user_id=user_id, username=username)
