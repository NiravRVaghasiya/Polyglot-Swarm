"""Map multimodal assessment results to LKM evidence (ADR-0034).

The rules:

- **One event per assessed dimension per submission.** A dimension that
  abstained produces no graded evidence.
- **Mapping to skills and subskills:**

  | dimension | skill | subskill |
  |---|---|---|
  | `fluency` | `speaking` | `fluency` |
  | `intelligibility` | `pronunciation` | `intelligibility` |
  | `pronunciation` | `pronunciation` | `acoustic_proxy` |
  | listening questions | `listening` | `recognition` / `comprehension` / `recall` |

- **Correlation.** Every event from one recording shares a correlation key
  and an item id derived from the audio's hash. Resubmitting the same audio
  therefore merges into one observation in the learner model, and is never
  counted twice. Listening questions are independent items.
- **Measures without a score.** A dimension that produced measures but no
  validated score is recorded as *practice exposure* (``assessment =
  "exposed"``). It counts toward coverage, never toward mastery.
- **Two kinds of confidence.** Transcript-derived events carry the
  recogniser's confidence in ``transcription_confidence``, separately from
  ``confidence`` (the reliability of the judgment about the learner). The
  learner model discounts by both (``src/learner/estimation.py``).
- **No transcript text in evidence.** Evidence stores no transcript text
  (``observed`` is empty): the transcript is a derived artifact of the
  submission, covered by its own retention and deletion rules.
"""

from __future__ import annotations

from typing import Any

from src.evidence.difficulty import cefr_to_difficulty
from src.evidence.events import DifficultyBasis, EventType, LearningEvent
from src.evidence.provenance import Provenance
from src.multimodal.contracts import AssessmentReport, DimensionResult, Status
from src.multimodal.listening import ListeningResult

SOURCE = "multimodal-v1"
RUBRIC = "multimodal-rubric-1.0"

_SPEAKING_MAP = {
    "fluency": ("speaking", "fluency", EventType.SKILL_EVIDENCE),
    "intelligibility": ("pronunciation", "intelligibility", EventType.PRONUNCIATION_EVENT),
    "pronunciation": ("pronunciation", "acoustic_proxy", EventType.PRONUNCIATION_EVENT),
}


def _processing(report: AssessmentReport) -> dict[str, Any]:
    return {
        "steps": [
            {
                "stage": s.stage,
                "status": s.status.value,
                "provider": s.provider,
                "model": s.model,
                "latency_ms": round(s.latency_ms, 1),
            }
            for s in report.steps
        ],
        "quality_issues": list(report.issues),
    }


def speaking_events(
    report: AssessmentReport,
    *,
    session_id: str | None = None,
    cefr: str | None = None,
    transcription_confidence: float | None = None,
    span: tuple[float, float] | None = None,
) -> list[LearningEvent]:
    """Evidence for the speaking dimensions of a report."""
    if report.asset is None:
        return []
    digest = report.asset.sha256[:16]
    difficulty = cefr_to_difficulty(cefr)
    provenance = Provenance(
        source=SOURCE, session_id=session_id, rubric_version=RUBRIC, model_version=None
    )
    media_ref: dict[str, Any] = {
        "asset_id": report.asset.asset_id,
        "submission_id": report.submission_id,
    }
    if span is not None:
        media_ref.update({"start": round(span[0], 2), "end": round(span[1], 2)})
    events: list[LearningEvent] = []
    for dim in report.dimensions:
        if dim.dimension not in _SPEAKING_MAP:
            continue
        skill, subskill, event_type = _SPEAKING_MAP[dim.dimension]
        graded = dim.status == Status.OK and dim.value is not None
        exposure = dim.status == Status.PARTIAL
        if not (graded or exposure):
            continue
        transcript_based = dim.basis in ("transcript", "timing", "acoustic_proxy")
        events.append(
            LearningEvent.create(
                event_type,
                report.user_id,
                report.language,
                provenance=provenance,
                skill=skill,
                subskill=subskill,
                objective_id=f"{skill}.{subskill}",
                item_id=f"utterance:{digest}",
                assessment="scored" if graded else "exposed",
                confidence=max(0.0, min(1.0, dim.confidence)) if graded else 1.0,
                task_type=f"speaking_{report.task_type}",
                difficulty=difficulty,
                difficulty_basis=DifficultyBasis.CEFR_LABEL if difficulty is not None else None,
                correlation_id=f"audio:{digest}",
                payload={
                    "score": None if dim.value is None else round(dim.value, 4),
                    "basis": dim.basis,
                    "measures": _plain_measures(dim),
                },
                modality="audio",
                media_ref=media_ref,
                processing=_processing(report),
                transcription_confidence=(
                    None
                    if not transcript_based or transcription_confidence is None
                    else round(max(0.0, min(1.0, transcription_confidence)), 4)
                ),
            )
        )
    return events


def _plain_measures(dim: DimensionResult) -> dict[str, Any]:
    return {
        k: (round(v, 4) if isinstance(v, float) else v)
        for k, v in dim.measures.items()
        if isinstance(v, (int, float, bool, str))
    }


def listening_events(
    result: ListeningResult,
    *,
    user_id: str,
    submission_id: str,
    session_id: str | None = None,
) -> list[LearningEvent]:
    """One graded event per answered question (unanswered ones are not evidence)."""
    task = result.task
    provenance = Provenance(source=SOURCE, session_id=session_id, rubric_version=RUBRIC)
    events = []
    for q in result.per_question:
        if not q["answered"]:
            continue
        events.append(
            LearningEvent.create(
                EventType.COMPREHENSION_RESULT,
                user_id,
                task.language,
                provenance=provenance,
                skill="listening",
                subskill=q["kind"],
                objective_id=f"listening.{q['kind']}",
                item_id=f"{task.task_id}:{q['question_id']}",
                assessment="correct" if q["correct"] else "incorrect",
                confidence=0.9 if q["kind"] != "recall" else 0.8,
                task_type=f"listening_{q['kind']}",
                difficulty=task.difficulty,
                difficulty_basis=DifficultyBasis.CEFR_LABEL,
                payload={
                    "task_id": task.task_id,
                    "voice": task.voice,
                    "accent": task.accent,
                    "rate": task.rate,
                    "basis": "response",
                },
                modality="audio",
                media_ref={"task_id": task.task_id, "submission_id": submission_id},
                processing={"steps": [{"stage": "score", "status": "ok", "provider": "rules"}]},
            )
        )
    return events
