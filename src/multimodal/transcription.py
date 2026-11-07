"""Speech-to-text as a processing stage (ADR-0034).

A :class:`SpeechToTextProvider` turns decoded audio into a :class:`Transcript`
that keeps:

- segments, with start and end times;
- per-word timestamps and probabilities, when the provider gives them;
- the detected language and its probability;
- a transcription confidence.

The LLM provider abstraction (``src/llm``) is text-only, so speech providers
get their own small protocol, built in the same way: concrete providers
only, explicit availability, error categories, retries for transient
failures, and no silent fallback to another provider.

``WhisperLocalProvider`` wraps local ``openai-whisper`` (the project's
``voice`` extra).

**Transcription confidence** is the duration-weighted mean word probability.
It describes the *recogniser*, not the learner. Whisper's probabilities are
not calibrated, and its word timestamps are approximate (about ±0.1–0.3 s).
Downstream assessors treat both as such.

**Repetition loops.** Whisper sometimes loops on a phrase ("the world, the
world, ...") while still reporting high word probabilities, so confidence
does not catch it. :attr:`Transcript.compression_ratio` (gzip ratio of the
text, Whisper's own heuristic and threshold :data:`COMPRESSION_RATIO_MAX`)
does; the pipeline abstains above it.
"""

from __future__ import annotations

import os
import tempfile
import time
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from src.multimodal.contracts import Observation, ProcessingStep, Status

#: Whisper language codes for the app's language names.
LANGUAGE_CODES = {
    "spanish": "es",
    "polish": "pl",
    "italian": "it",
    "french": "fr",
    "german": "de",
    "english": "en",
    "portuguese": "pt",
}
#: Languages the local Whisper model supports (subset relevant to the app).
WHISPER_SUPPORTED = frozenset({"es", "pl", "it", "fr", "de", "en", "pt", "nl", "ca"})


#: Whisper's default ``compression_ratio_threshold``: above it, the text is a
#: degenerate repetition loop rather than speech.
COMPRESSION_RATIO_MAX = 2.4


def language_code(language: str | None) -> str | None:
    if not language:
        return None
    key = language.strip().lower()
    if key in LANGUAGE_CODES:
        return LANGUAGE_CODES[key]
    return key if len(key) == 2 else None


class TranscriptionError(RuntimeError):
    """A provider failure; ``category`` is one of the documented categories."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category  # unavailable | unsupported_language | timeout | error


@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float | None


@dataclass
class Segment:
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    text: str
    language: str | None
    language_probability: float | None
    segments: list[Segment]
    provider: str
    model: str

    @property
    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]

    @property
    def confidence(self) -> float | None:
        """Duration-weighted mean word probability (``None`` without word probabilities)."""
        words = [w for w in self.words if w.probability is not None]
        if not words:
            return None
        weights = [max(w.end - w.start, 0.05) for w in words]
        return sum((w.probability or 0.0) * wt for w, wt in zip(words, weights, strict=True)) / sum(
            weights
        )

    @property
    def compression_ratio(self) -> float:
        """Bytes / gzip bytes of the text; high values mean a repetition loop."""
        raw = self.text.strip().encode("utf-8")
        return len(raw) / len(zlib.compress(raw)) if raw else 0.0

    @property
    def repetition_loop(self) -> bool:
        return self.compression_ratio > COMPRESSION_RATIO_MAX

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "language_probability": self.language_probability,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "provider": self.provider,
            "model": self.model,
            "segments": [asdict(s) for s in self.segments],
        }


class SpeechToTextProvider(Protocol):
    name: str
    model: str

    def available(self) -> bool: ...

    def transcribe(self, wav_bytes: bytes, *, language: str | None) -> Transcript: ...


class WhisperLocalProvider:
    """Local Whisper (``openai-whisper``); CPU or GPU, no network after model download."""

    name = "whisper-local"

    def __init__(self, model: str = "base") -> None:
        self.model = model
        self._model: Any = None

    def available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("whisper") is not None

    def _load(self) -> Any:
        if self._model is None:
            try:
                import whisper  # type: ignore[import-not-found, import-untyped, unused-ignore]
            except ImportError as exc:
                raise TranscriptionError(
                    "unavailable", "openai-whisper is not installed (voice extra)"
                ) from exc
            self._model = whisper.load_model(self.model)
        return self._model

    def transcribe(self, wav_bytes: bytes, *, language: str | None) -> Transcript:
        import whisper  # type: ignore[import-not-found, import-untyped, unused-ignore]

        code = language_code(language)
        if code is not None and code not in WHISPER_SUPPORTED:
            raise TranscriptionError("unsupported_language", f"language {code!r} not supported")
        model = self._load()
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes)
            audio = whisper.load_audio(path)
            mel = whisper.log_mel_spectrogram(
                whisper.pad_or_trim(audio), n_mels=model.dims.n_mels
            ).to(model.device)
            _, probs = model.detect_language(mel)
            detected = max(probs, key=probs.get)
            result = model.transcribe(
                audio,
                language=code,
                word_timestamps=True,
                temperature=0.0,
                condition_on_previous_text=False,
                fp16=False,
            )
        finally:
            os.unlink(path)
        # Whisper's own no-speech rule: a segment it considers non-speech and
        # decodes with low likelihood is a hallucination, not a transcript.
        kept = [
            s
            for s in result.get("segments", [])
            if not (
                float(s.get("no_speech_prob", 0.0)) > 0.6
                and float(s.get("avg_logprob", 0.0)) < -1.0
            )
        ]
        segments = [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=str(s["text"]).strip(),
                avg_logprob=float(s.get("avg_logprob", 0.0)),
                no_speech_prob=float(s.get("no_speech_prob", 0.0)),
                words=[
                    Word(
                        text=str(w["word"]).strip(),
                        start=float(w["start"]),
                        end=float(w["end"]),
                        probability=float(w.get("probability", 0.0)),
                    )
                    for w in s.get("words", [])
                ],
            )
            for s in kept
        ]
        return Transcript(
            text=" ".join(seg.text for seg in segments).strip(),
            language=detected,
            language_probability=float(probs.get(detected, 0.0)),
            segments=segments,
            provider=self.name,
            model=f"whisper-{self.model}",
        )


_DEFAULT: dict[str, WhisperLocalProvider] = {}


def default_provider(model: str = "base") -> WhisperLocalProvider:
    """A process-wide Whisper provider (the model loads once)."""
    if model not in _DEFAULT:
        _DEFAULT[model] = WhisperLocalProvider(model)
    return _DEFAULT[model]


def run_transcription(
    provider: SpeechToTextProvider,
    asset_id: str,
    wav_bytes: bytes,
    *,
    language: str | None,
    max_attempts: int = 2,
) -> tuple[Observation | None, ProcessingStep]:
    """Transcribe with retries for transient errors. Never raises.

    Returns ``(observation, step)``. The observation is ``None`` when
    transcription failed. ``unavailable`` and ``unsupported_language`` are not
    retried; generic errors are.
    """
    start = time.perf_counter()
    attempts = 0
    last: TranscriptionError | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            if not provider.available():
                raise TranscriptionError("unavailable", f"{provider.name} is not available")
            transcript = provider.transcribe(wav_bytes, language=language)
            step = ProcessingStep(
                stage="transcribe",
                status=Status.OK,
                provider=provider.name,
                model=transcript.model,
                latency_ms=(time.perf_counter() - start) * 1000,
                attempts=attempts,
            )
            return (
                Observation(
                    kind="transcript",
                    asset_id=asset_id,
                    data={"transcript": transcript},
                    processing_confidence=transcript.confidence,
                    step=step,
                ),
                step,
            )
        except TranscriptionError as exc:
            last = exc
            if exc.category in ("unavailable", "unsupported_language"):
                break
        except Exception as exc:  # noqa: BLE001 - provider bugs become a failed step
            last = TranscriptionError("error", type(exc).__name__)
    assert last is not None
    return None, ProcessingStep(
        stage="transcribe",
        status=Status.FAILED,
        provider=provider.name,
        model=getattr(provider, "model", None),
        latency_ms=(time.perf_counter() - start) * 1000,
        attempts=attempts,
        error_category=last.category,
        detail=str(last),
    )
