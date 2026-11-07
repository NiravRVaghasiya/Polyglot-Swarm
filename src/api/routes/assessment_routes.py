"""Multimodal assessment routes (ADR-0034): speaking and listening.

All routes are authenticated and scoped to the caller's user id.

- ``POST /api/v1/assessment/speaking`` — assess a recording. A validation
  failure returns 4xx with a stable ``code``. Otherwise the response is 200
  with a report whose ``status`` is ``ok``, ``partial``, ``abstained`` or
  ``failed``; a provider failure is a ``failed`` report, not a 500.
- ``GET /api/v1/assessment/listening/tasks`` — the listening tasks for a
  language, without scripts or answers.
- ``GET /api/v1/assessment/listening/tasks/{id}/audio`` — the synthesised
  stimulus, or 503 when TTS is unavailable.
- ``POST /api/v1/assessment/listening/tasks/{id}/answers`` — score answers.
- ``GET`` / ``DELETE /api/v1/assessment/submissions[/{id}]`` — the caller's
  own submissions.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.deps import get_current_user

router = APIRouter(prefix="/api/v1/assessment", tags=["assessment"])


class SpeakingRequest(BaseModel):
    audio_base64: str
    audio_format: str | None = None
    language: str = "Spanish"
    task_type: Literal["free_speech", "read_aloud"] = "free_speech"
    target_text: str | None = Field(default=None, max_length=1000)
    cefr: str | None = None
    session_id: str | None = None
    #: Analyse grammar of free speech from the transcript (uses the LLM).
    analyze_grammar: bool = False
    #: Explicit consent to keep the raw recording (default: not kept).
    retain_audio: bool = False


class ListeningAnswers(BaseModel):
    answers: dict[str, str | None]
    session_id: str | None = None


@router.post("/speaking")
async def speaking(
    req: SpeakingRequest, user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    from src.multimodal.audio import AudioValidationError
    from src.multimodal.pipeline import assess_speaking
    from src.multimodal.speaking import SpeakingTask

    if req.task_type == "read_aloud" and not (req.target_text or "").strip():
        raise HTTPException(status_code=422, detail="read_aloud needs target_text")
    try:
        data = base64.b64decode(req.audio_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail={"code": "invalid_base64", "message": "invalid base64"}
        ) from exc
    try:
        outcome = await assess_speaking(
            data,
            user_id=user_id,
            language=req.language,
            task=SpeakingTask(req.task_type, req.target_text, req.cefr, req.language),
            declared_format=req.audio_format,
            session_id=req.session_id,
            analyze_grammar=req.analyze_grammar,
            retain_audio=req.retain_audio,
        )
    except AudioValidationError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    return outcome.report.as_dict()


@router.get("/listening/tasks")
def listening_tasks(
    language: str = "Spanish", user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    from src.multimodal.listening import tasks_for

    return {"tasks": [t.public() for t in tasks_for(language)]}


def _task(task_id: str) -> Any:
    from src.multimodal.listening import task_bank

    task = task_bank().get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="unknown listening task")
    return task


@router.get("/listening/tasks/{task_id}/audio")
async def listening_audio(task_id: str, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    from src.speech.stt import SpeechDependencyError
    from src.speech.tts import synthesize

    task = _task(task_id)
    try:
        audio = await synthesize(task.script, voice=task.voice, rate=task.rate)
    except SpeechDependencyError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - TTS outage is a 503
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="speech synthesis unavailable"
        ) from exc
    return {
        "task_id": task_id,
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "audio_format": "mp3",
    }


@router.post("/listening/tasks/{task_id}/answers")
def listening_answers(
    task_id: str, req: ListeningAnswers, user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    from src.multimodal.pipeline import assess_listening

    task = _task(task_id)
    known = {q.question_id for q in task.questions}
    unknown = set(req.answers) - known
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown question ids: {sorted(unknown)}")
    report, _ = assess_listening(task, req.answers, user_id=user_id, session_id=req.session_id)
    return report.as_dict()


@router.get("/submissions")
def submissions(
    language: str | None = None, limit: int = 20, user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    from src.multimodal import store

    return {"submissions": store.list_submissions(user_id, language, limit=max(1, min(limit, 200)))}


@router.get("/submissions/{submission_id}")
def submission(submission_id: str, user_id: str = Depends(get_current_user)) -> dict[str, Any]:
    from src.multimodal import store

    row = store.get_submission(user_id, submission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


@router.delete("/submissions/{submission_id}")
def delete_submission(
    submission_id: str, user_id: str = Depends(get_current_user)
) -> dict[str, Any]:
    from src.multimodal import store

    if not store.delete_submission(user_id, submission_id):
        raise HTTPException(status_code=404, detail="not found")
    return {"deleted": submission_id}
