"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# --- Auth ---
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


class UserResponse(BaseModel):
    user_id: str
    username: str


# --- Sessions & chat ---
class StartSessionRequest(BaseModel):
    language: str | None = None
    scenario_id: str | None = None


class StartSessionResponse(BaseModel):
    session_id: str
    language: str
    cefr_level: str
    opening_line: str = ""


class ChatRequest(BaseModel):
    session_id: str
    message: str


class HiddenFeedback(BaseModel):
    grammar: list[dict[str, Any]] = []
    vocabulary: list[dict[str, Any]] = []
    cultural: list[str] = []


class ChatResponse(BaseModel):
    reply: str
    hidden_feedback: HiddenFeedback


class SessionStateResponse(BaseModel):
    session_id: str
    language: str
    turn_count: int
    cefr_level: str


class EndSessionResponse(BaseModel):
    report: str
    persisted: dict[str, int]


# --- Review ---
class ReviewSubmitRequest(BaseModel):
    word: str
    correct: bool


# --- Profile ---
class ProfileUpdateRequest(BaseModel):
    native_language: str | None = None
    target_languages: list[str] | None = None
    goals: list[str] | None = None
    interests: list[str] | None = None
    cefr_by_language: dict[str, str] | None = None
