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


# --- Voice ---
class TranscribeRequest(BaseModel):
    #: Base64-encoded audio (the browser's recorded blob).
    audio_base64: str
    #: File extension/format hint for the temp file Whisper reads (e.g. "webm",
    #: "wav", "ogg"). Defaults to wav.
    audio_format: str = "wav"
    #: Free-form language name to hint the transcriber (optional).
    language: str | None = None


class TranscribeResponse(BaseModel):
    transcript: str


class TtsRequest(BaseModel):
    text: str
    language: str | None = None


class TtsResponse(BaseModel):
    audio_base64: str
    audio_format: str = "mp3"


# --- Profile ---
class ProfileUpdateRequest(BaseModel):
    native_language: str | None = None
    target_languages: list[str] | None = None
    goals: list[str] | None = None
    interests: list[str] | None = None
    cefr_by_language: dict[str, str] | None = None


# --- Learner model: plan, CEFR profile, skill map, insights (Phase 16) ---
class PlanAction(BaseModel):
    type: str
    target: str
    skill: str | None = None
    reason: str = ""
    priority: float = 0.0
    estimated_minutes: float = 0.0


class PlanResponse(BaseModel):
    language: str
    goal: str
    actions: list[PlanAction] = []


class SkillAssessmentResponse(BaseModel):
    # ``skill`` is redundant (it is the dict key in CEFRProfileResponse.skills)
    # so it is optional here.
    skill: str | None = None
    cefr: str
    mastery: float
    confidence: float
    sample_size: int


class CEFRProfileResponse(BaseModel):
    language: str
    overall: str
    skills: dict[str, SkillAssessmentResponse] = {}


class SkillBeliefResponse(BaseModel):
    skill: str
    mastery: float
    uncertainty: float
    sample_size: int


class SkillMapResponse(BaseModel):
    language: str
    skills: list[SkillBeliefResponse] = []


class InsightsResponse(BaseModel):
    language: str
    current_cefr: str | None = None
    overall_cefr: str
    weakest_skills: list[str] = []
    top_weaknesses: list[dict[str, Any]] = []
    recommended_focus: list[str] = []
    streak: int = 0


# --- Privacy: self-service export/deletion (Phase 21) ---
class DataExportResponse(BaseModel):
    data: dict[str, Any]


class DataDeletionResponse(BaseModel):
    deleted: dict[str, Any]


# --- Cost/latency visibility (Phase 22) ---
class CostSummaryResponse(BaseModel):
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    mean_latency_ms: float = 0.0
    failures: int = 0
    by_tier: dict[str, dict[str, Any]] = {}


# --- Observability: trace (Phase 17) ---
class TraceSpanResponse(BaseModel):
    kind: str  # "model_run" | "evidence"
    timestamp: str
    interaction_id: str | None = None
    summary: str
    detail: dict[str, Any] = {}


class TraceResponse(BaseModel):
    session_id: str
    user_id: str
    interactions: list[str] = []
    spans: list[TraceSpanResponse] = []
