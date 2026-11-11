"""Modality-neutral data contracts for multimodal assessment (ADR-0034).

The pipeline has five separate stages. Each one hands a typed value to the
next, and none reaches back into an earlier one:

    capture/ingest  -> MediaAsset (+ decoded signal, quality report)
    process         -> Observation (e.g. a Transcript, signal features)
    assess          -> AssessmentReport (per-dimension results, or abstentions)
    validate        -> list[LearningEvent] (evidence, with provenance)
    LKM update      -> the existing knowledge model (Phase 1)

A new modality (image, video, real-time stream) adds its own ingestor and
processors that produce ``Observation`` values. It also adds the assessors
that read them. The assessment report, evidence mapping and LKM stages stay
unchanged.

Two kinds of uncertainty are kept apart throughout:

- ``processing_confidence``: how much the *machine processing* can be trusted
  (e.g. transcription confidence);
- ``confidence`` of an assessment: how much the judgment about the *learner*
  can be trusted.

A low-quality recording lowers the first. It must never be read as low
learner ability.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Modality(StrEnum):
    TEXT = "text"
    AUDIO = "audio"
    # Reserved for later phases; no ingestor exists yet.
    IMAGE = "image"
    VIDEO = "video"


class Status(StrEnum):
    """Outcome of a stage or of one assessment dimension."""

    OK = "ok"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class MediaAsset:
    """One captured input. Raw bytes are *not* part of the asset."""

    asset_id: str
    user_id: str
    modality: Modality
    media_format: str  # sniffed container, e.g. "wav", "webm"
    sha256: str
    size_bytes: int
    duration_s: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    language: str | None = None
    created_at: str = field(default_factory=now_iso)
    #: Whether the raw media is kept, and until when (see the privacy policy).
    retained: bool = False
    retain_until: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["modality"] = self.modality.value
        return data


@dataclass
class ProcessingStep:
    """Provenance and performance of one stage run."""

    stage: str  # ingest | transcribe | features | assess | evidence
    status: Status
    provider: str | None = None
    model: str | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    attempts: int = 1
    error_category: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class Observation:
    """A processed, modality-specific view of an asset (e.g. a transcript)."""

    kind: str  # transcript | signal_features | ...
    asset_id: str
    data: dict[str, Any]
    processing_confidence: float | None
    step: ProcessingStep


@dataclass
class DimensionResult:
    """One assessed dimension (fluency, intelligibility, comprehension, ...).

    ``basis`` says what the judgment rests on:

    - ``acoustic``: the audio signal;
    - ``transcript``: the ASR text;
    - ``timing``: word or pause timing;
    - ``response``: the learner's answer to a task.

    It is never left implicit. An abstention carries a reason and no value.
    """

    dimension: str
    status: Status
    basis: str
    value: float | None = None  # in [0, 1] when assessed
    confidence: float = 0.0
    measures: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    feedback: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class AssessmentReport:
    """Everything one submission produced, including partial results."""

    submission_id: str
    user_id: str
    language: str
    task_type: str
    modality: Modality
    asset: MediaAsset | None
    status: Status
    dimensions: list[DimensionResult] = field(default_factory=list)
    steps: list[ProcessingStep] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def dimension(self, name: str) -> DimensionResult | None:
        return next((d for d in self.dimensions if d.dimension == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "user_id": self.user_id,
            "language": self.language,
            "task_type": self.task_type,
            "modality": self.modality.value,
            "asset": None if self.asset is None else self.asset.as_dict(),
            "status": self.status.value,
            "dimensions": [d.as_dict() for d in self.dimensions],
            "steps": [s.as_dict() for s in self.steps],
            "observations": self.observations,
            "quality": self.quality,
            "issues": list(self.issues),
            "evidence_ids": list(self.evidence_ids),
            "created_at": self.created_at,
        }
