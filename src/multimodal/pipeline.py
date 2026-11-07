"""Multimodal assessment orchestration (ADR-0034).

``assess_speaking`` runs each stage separately and records it:

1. **ingest** — validate and decode, then a quality report. Invalid input
   raises :class:`~src.multimodal.audio.AudioValidationError`, which the API
   maps to 4xx.
2. **gate** — abstain early when nothing can be assessed:
   - no speech detected;
   - a recognisable but different language;
   - a language Whisper does not support;
   - (after transcription) a recogniser repetition loop.

   The recogniser is never run on silence, because Whisper invents text for
   silent audio.
3. **transcribe** — through a :class:`SpeechToTextProvider`, with retries.
   On failure the report is ``failed``, but the quality report is still
   returned.
4. **assess** — fluency, intelligibility and pronunciation, each with
   abstention. Spoken grammar, when requested for free speech with a
   confident transcript, uses the existing grammar agent.
5. **evidence** — map to events and record them, then update the learner
   model.

The report status is:

- ``ok`` — every dimension was assessed;
- ``partial`` — some dimensions abstained;
- ``abstained`` — nothing was assessed;
- ``failed`` — a provider failure.

Every stage's latency and outcome is in ``report.steps``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from src.multimodal.audio import DEFAULT_LIMITS, AudioLimits, ingest_audio
from src.multimodal.contracts import (
    AssessmentReport,
    DimensionResult,
    Modality,
    ProcessingStep,
    Status,
)
from src.multimodal.evidence import listening_events, speaking_events
from src.multimodal.listening import ListeningTask, score_answers
from src.multimodal.speaking import SpeakingTask
from src.multimodal.speaking import assess_speaking as assess_speaking_dims
from src.multimodal.transcription import (
    WHISPER_SUPPORTED,
    SpeechToTextProvider,
    Transcript,
    default_provider,
    language_code,
    run_transcription,
)

logger = logging.getLogger("polyglot.multimodal")

#: A detected language this sure and different from the expected one abstains.
LANGUAGE_MISMATCH_PROB = 0.6
#: Spoken grammar is only analysed above this transcription confidence.
GRAMMAR_MIN_TRANSCRIPT_CONFIDENCE = 0.75


@dataclass
class SpeakingOutcome:
    report: AssessmentReport
    events: list[Any]
    transcript: Transcript | None


def _status(dims: list[DimensionResult]) -> Status:
    assessed = [d for d in dims if d.status in (Status.OK, Status.PARTIAL)]
    if not assessed:
        return Status.ABSTAINED
    if len(assessed) == len(dims) and all(d.status == Status.OK for d in dims):
        return Status.OK
    return Status.PARTIAL


def _abstain_all(report: AssessmentReport, reason: str) -> None:
    report.dimensions = [
        DimensionResult(name, Status.ABSTAINED, basis, reason=reason)
        for name, basis in (
            ("fluency", "timing"),
            ("intelligibility", "transcript"),
            ("pronunciation", "acoustic_proxy"),
        )
    ]
    report.status = Status.ABSTAINED


async def _spoken_grammar(
    transcript: Transcript, task: SpeakingTask, report: AssessmentReport
) -> tuple[DimensionResult, list[Any]]:
    """Grammar of free speech via the existing grammar agent (transcript basis)."""
    conf = transcript.confidence or 0.0
    if task.task_type != "free_speech":
        return DimensionResult(
            "spoken_grammar",
            Status.ABSTAINED,
            "transcript",
            reason="read-aloud text is given, not produced: no grammar evidence",
        ), []
    if conf < GRAMMAR_MIN_TRANSCRIPT_CONFIDENCE:
        return DimensionResult(
            "spoken_grammar",
            Status.ABSTAINED,
            "transcript",
            reason=f"transcript confidence {conf:.2f}: recogniser errors could look like "
            "learner errors",
        ), []
    from src.agents.grammar import grammar_node
    from src.evidence.extractor import extract_grammar_events
    from src.evidence.provenance import Provenance

    start = time.perf_counter()
    result = await grammar_node(
        {
            "last_user_input": transcript.text,
            "language": report.language,
            "cefr_level": task.cefr or "A2",
            "grammar_weaknesses": [],
            "grammar_errors": [],
        }  # type: ignore[typeddict-item]
    )
    errors = result.get("grammar_errors", [])
    report.steps.append(
        ProcessingStep(
            stage="spoken_grammar",
            status=Status.OK,
            provider="grammar-agent",
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    )
    digest = report.asset.sha256[:16] if report.asset else report.submission_id
    events = [
        e.model_copy(
            update={
                "modality": "audio",
                "transcription_confidence": round(conf, 4),
                "media_ref": {"submission_id": report.submission_id},
                "correlation_id": f"audio:{digest}:{e.subskill}",
                "observed": None,  # no transcript text in evidence
                "task_type": "speaking_free_speech",
            }
        )
        for e in extract_grammar_events(
            report.user_id,
            report.language,
            [dict(err) for err in errors],
            provenance=Provenance(source="multimodal-v1"),
        )
    ]
    return DimensionResult(
        "spoken_grammar",
        Status.OK,
        "transcript",
        confidence=round(conf, 4),
        measures={"errors_found": len(errors)},
        reason="from the transcript; recogniser auto-correction can hide errors",
    ), events


async def assess_speaking(
    data: bytes,
    *,
    user_id: str,
    language: str,
    task: SpeakingTask,
    declared_format: str | None = None,
    provider: SpeechToTextProvider | None = None,
    session_id: str | None = None,
    analyze_grammar: bool = False,
    record: bool = True,
    retain_audio: bool = False,
    limits: AudioLimits = DEFAULT_LIMITS,
) -> SpeakingOutcome:
    """Run the speaking pipeline end to end (see module docstring)."""
    t0 = time.perf_counter()
    ingested = ingest_audio(
        data, user_id=user_id, declared_format=declared_format, language=language, limits=limits
    )
    report = AssessmentReport(
        submission_id=uuid.uuid4().hex,
        user_id=user_id,
        language=language,
        task_type=task.task_type,
        modality=Modality.AUDIO,
        asset=ingested.asset,
        status=Status.PARTIAL,
        quality=ingested.quality.as_dict(),
        issues=list(ingested.quality.issues),
    )
    report.steps.append(
        ProcessingStep(
            stage="ingest",
            status=Status.OK,
            provider="ffmpeg+stdlib",
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    )
    code = language_code(language)
    transcript: Transcript | None = None
    events: list[Any] = []
    if "no_speech_detected" in report.issues:
        _abstain_all(report, "no speech detected in the recording")
    elif code is None or code not in WHISPER_SUPPORTED:
        _abstain_all(report, f"language {language!r} is not supported for speech assessment")
        report.issues.append("unsupported_language")
    else:
        provider = provider or default_provider()
        observation, step = run_transcription(
            provider, ingested.asset.asset_id, ingested.wav_bytes(), language=language
        )
        report.steps.append(step)
        if observation is None:
            _abstain_all(report, f"transcription failed ({step.error_category})")
            report.status = Status.FAILED
        else:
            transcript = observation.data["transcript"]
            assert isinstance(transcript, Transcript)
            report.observations["transcript"] = transcript.as_dict()
            if (
                code is not None
                and transcript.language not in (None, code)
                and (transcript.language_probability or 0.0) >= LANGUAGE_MISMATCH_PROB
            ):
                report.issues.append("language_mismatch")
                _abstain_all(
                    report,
                    f"the recording sounds like {transcript.language!r}, not {code!r}",
                )
            elif transcript.repetition_loop:
                report.issues.append("repetition_loop")
                _abstain_all(
                    report, "the recogniser produced a repetition loop; the transcript is unusable"
                )
            else:
                a0 = time.perf_counter()
                report.dimensions = assess_speaking_dims(
                    transcript, task, language_code=code, quality_issues=report.issues
                )
                if analyze_grammar:
                    dim, grammar_events = await _spoken_grammar(transcript, task, report)
                    report.dimensions.append(dim)
                    events += grammar_events
                report.steps.append(
                    ProcessingStep(
                        stage="assess",
                        status=Status.OK,
                        provider="rules",
                        latency_ms=(time.perf_counter() - a0) * 1000,
                    )
                )
                report.status = _status(report.dimensions)
    if transcript is not None and report.status not in (Status.FAILED, Status.ABSTAINED):
        words = transcript.words
        span = (words[0].start, words[-1].end) if words else None
        events = (
            speaking_events(
                report,
                session_id=session_id,
                cefr=task.cefr,
                transcription_confidence=transcript.confidence,
                span=span,
            )
            + events
        )
    report.evidence_ids = [e.event_id for e in events]
    if record:
        _record(report, events, raw=data, retain_audio=retain_audio)
    logger.info(
        "speaking assessed: id=%s status=%s events=%d",
        report.submission_id, report.status.value, len(events),
    )  # fmt: skip
    return SpeakingOutcome(report=report, events=events, transcript=transcript)


def assess_listening(
    task: ListeningTask,
    answers: dict[str, str | None],
    *,
    user_id: str,
    session_id: str | None = None,
    record: bool = True,
) -> tuple[AssessmentReport, list[Any]]:
    """Score a listening submission (no transcription involved)."""
    result = score_answers(task, answers)
    report = AssessmentReport(
        submission_id=uuid.uuid4().hex,
        user_id=user_id,
        language=task.language,
        task_type="listening",
        modality=Modality.AUDIO,
        asset=None,
        status=_status(result.dimensions),
        dimensions=result.dimensions,
        steps=[ProcessingStep(stage="score", status=Status.OK, provider="rules")],
        observations={
            "task": {"task_id": task.task_id, "cefr": task.cefr, "voice": task.voice},
            "per_question": result.per_question,
        },
    )
    events = listening_events(
        result, user_id=user_id, submission_id=report.submission_id, session_id=session_id
    )
    report.evidence_ids = [e.event_id for e in events]
    if record:
        _record(report, events)
    return report, events


def _record(
    report: AssessmentReport,
    events: list[Any],
    *,
    raw: bytes | None = None,
    retain_audio: bool = False,
) -> None:
    from src.evidence import store as evidence_store
    from src.learner import get_knowledge_model
    from src.multimodal import store

    store.save_submission(report, raw=raw, retain_audio=retain_audio)
    store.purge_expired()
    if events:
        evidence_store.record_events(events)
        get_knowledge_model().update_from_events(
            report.user_id, report.language, [e.model_dump() for e in events]
        )
