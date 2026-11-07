"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --- Auth ---
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
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
    #: Optional FSRS rating (1=Again .. 4=Easy); defaults to 3 if correct, else 1.
    rating: int | None = Field(default=None, ge=1, le=4)
    #: What the review asked for: "recognition" or "production" (ADR-0033).
    mode: Literal["recognition", "production"] | None = None


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
# ADR-0031: CEFR bands and mastery are nullable (no evidence -> no level, never
# a default or a zero), every estimate carries an evidence ``status``, and
# ``confidence`` is an ordinal evidence index, not a calibrated probability.

#: insufficient_evidence | provisional | estimated | validated
EvidenceStatusValue = str


class PlanAction(BaseModel):
    type: str
    target: str
    skill: str | None = None
    reason: str = ""
    priority: float = 0.0
    estimated_minutes: float = 0.0
    #: assessment | remediation | reinforcement | advancement ("" if unknown)
    intent: str = ""


class PlanResponse(BaseModel):
    language: str
    goal: str
    actions: list[PlanAction] = []


class SkillAssessmentResponse(BaseModel):
    # ``skill`` is redundant (it is the dict key in CEFRProfileResponse.skills)
    # so it is optional here.
    skill: str | None = None
    cefr: str | None = None
    status: EvidenceStatusValue = "insufficient_evidence"
    mastery: float | None = None
    mastery_low: float | None = None
    mastery_high: float | None = None
    uncertainty: float = 1.0
    #: Evidence index in [0, 1] — ordinal, not a probability.
    confidence: float = 0.0
    confidence_label: str = "none"
    #: Raw graded observations (duplicates included).
    sample_size: int = 0
    independent_count: int = 0
    distinct_items: int = 0
    coverage: dict[str, Any] = {}
    #: The pre-ADR-0031 engine's mastery over the same evidence, for comparison.
    baseline_mastery: float | None = None


class CEFRProfileResponse(BaseModel):
    language: str
    overall: str | None = None
    overall_status: EvidenceStatusValue = "insufficient_evidence"
    overall_basis: list[str] = []
    unassessed_skills: list[str] = []
    method: str = ""
    skills: dict[str, SkillAssessmentResponse] = {}


class SkillBeliefResponse(BaseModel):
    skill: str
    mastery: float | None = None
    uncertainty: float
    #: Raw graded observations (duplicates included).
    sample_size: int
    status: EvidenceStatusValue = "insufficient_evidence"
    mastery_low: float | None = None
    mastery_high: float | None = None
    independent_count: int = 0
    effective_n: float = 0.0
    evidence_index: float = 0.0
    evidence_quality: float = 0.0
    coverage: dict[str, Any] = {}
    last_evidence_at: str | None = None


class SkillMapResponse(BaseModel):
    language: str
    method: str = ""
    skills: list[SkillBeliefResponse] = []


class InsightsResponse(BaseModel):
    language: str
    #: The tutor's working level from session logs (an instructional setting,
    #: not an assessment); ``None`` until a session produced a signal.
    current_cefr: str | None = None
    overall_cefr: str | None = None
    overall_status: EvidenceStatusValue = "insufficient_evidence"
    #: Lowest-mastery skills among those with provisional-or-better evidence.
    weakest_skills: list[str] = []
    #: Skills without enough evidence to judge (not assumed weak).
    needs_assessment: list[str] = []
    top_weaknesses: list[dict[str, Any]] = []
    recommended_focus: list[str] = []
    streak: int = 0


class EvidenceContributionResponse(BaseModel):
    event_id: str
    role: str  # counted | merged | exposure | ignored
    group_key: str
    item_key: str
    signal: float | None = None
    reliability: float = 0.0
    recency: float = 1.0
    repetition: float = 1.0
    difficulty_factor: float = 1.0
    difficulty_logit: float = 0.0
    weight: float = 0.0
    merged_into: str | None = None


class SkillExplanationResponse(BaseModel):
    language: str
    skill: str
    estimate: dict[str, Any]
    contributions: list[EvidenceContributionResponse] = []


class MasteryUpdateResponse(BaseModel):
    run_id: int
    skill: str
    method: str
    evidence_digest: str
    mastery_before: float | None = None
    mastery_after: float | None = None
    uncertainty_after: float | None = None
    status_before: str | None = None
    status_after: str | None = None
    baseline_mastery: float | None = None
    independent_n: float | None = None
    new_event_ids: list[str] = []
    removed_event_ids: list[str] = []
    created_at: str


class LearnerHistoryResponse(BaseModel):
    language: str
    updates: list[MasteryUpdateResponse] = []


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
