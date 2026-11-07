"""Audio ingestion: validation, decoding and signal-quality analysis (ADR-0034).

Every submitted recording passes through :func:`ingest_audio` before any
model sees it.

1. **Size limit** — :data:`AudioLimits.max_bytes`.
2. **Format** — the container is *sniffed* from its magic bytes. A declared
   format that disagrees with the sniffed one is rejected, not trusted.
3. **Decoding** to 16 kHz mono 16-bit PCM. A plain 16 kHz mono PCM WAV is
   read with the standard library; everything else goes through ffmpeg,
   which must be on ``PATH`` and runs with a timeout.
4. **Duration limits.**
5. **Signal quality** — RMS level, peak, clipping, the share of frames
   above the noise floor (speech activity), an SNR estimate, and the voiced
   regions.

Quality problems are not errors: the recording is accepted with
``issues``, and downstream assessors decide whether to abstain. Every
rejection is an :class:`AudioValidationError` with a stable ``code``.

Raw audio is never logged. Only sizes, formats, durations and hashes are.
"""

from __future__ import annotations

import io
import logging
import math
import shutil
import subprocess
import uuid
import wave
from array import array
from dataclasses import asdict, dataclass, field
from typing import Any

from src.multimodal.contracts import MediaAsset, Modality, sha256_hex

logger = logging.getLogger("polyglot.multimodal.audio")

SAMPLE_RATE = 16_000
FRAME_MS = 30
SUPPORTED_FORMATS = ("wav", "webm", "ogg", "mp3", "mp4", "flac")


@dataclass(frozen=True)
class AudioLimits:
    max_bytes: int = 10 * 1024 * 1024
    min_duration_s: float = 0.3
    max_duration_s: float = 120.0
    decode_timeout_s: float = 30.0


DEFAULT_LIMITS = AudioLimits()


class AudioValidationError(ValueError):
    """A recording that cannot be accepted. ``code`` is stable for clients."""

    def __init__(self, code: str, message: str, *, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def sniff_format(data: bytes) -> str | None:
    """Identify the container from magic bytes (``None`` if unknown)."""
    if len(data) < 12:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"  # Matroska/WebM
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[4:8] == b"ftyp":
        return "mp4"
    if data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


_ALIASES = {"m4a": "mp4", "mpeg": "mp3", "oga": "ogg", "opus": "ogg", "wave": "wav", "mkv": "webm"}


def _normalize_declared(fmt: str | None) -> str | None:
    if not fmt:
        return None
    key = fmt.strip().lower().lstrip(".").split(";")[0].split("/")[-1]
    return _ALIASES.get(key, key)


def _read_plain_wav(data: bytes) -> tuple[bytes, int, int] | None:
    """(pcm16, sample_rate, channels) for an uncompressed 16-bit WAV, else None."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
                return None
            return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()
    except (wave.Error, EOFError):
        return None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg_decode(data: bytes, timeout_s: float) -> bytes:
    if not ffmpeg_available():
        raise AudioValidationError(
            "decoder_unavailable",
            "ffmpeg is required to decode this audio format but is not installed",
            http_status=503,
        )
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1",
    ]  # fmt: skip
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, input=data, capture_output=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioValidationError("decode_timeout", "decoding the audio timed out") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise AudioValidationError("undecodable", "the audio could not be decoded")
    return proc.stdout


def decode_to_pcm16(data: bytes, fmt: str, *, timeout_s: float = 30.0) -> bytes:
    """Decode any supported container to 16 kHz mono PCM16."""
    if fmt == "wav":
        plain = _read_plain_wav(data)
        if plain is not None and plain[1] == SAMPLE_RATE and plain[2] == 1:
            return plain[0]
    return _ffmpeg_decode(data, timeout_s)


@dataclass
class AudioQuality:
    duration_s: float
    rms_dbfs: float
    peak: float
    clipping_ratio: float
    speech_ratio: float
    snr_db: float | None
    voiced_regions: list[tuple[float, float]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["voiced_regions"] = [[round(a, 3), round(b, 3)] for a, b in self.voiced_regions]
        for k in ("duration_s", "rms_dbfs", "peak", "clipping_ratio", "speech_ratio"):
            data[k] = round(float(data[k]), 4)
        data["snr_db"] = None if self.snr_db is None else round(self.snr_db, 2)
        return data


#: Quality thresholds (documented in docs/multimodal-assessment.md).
SILENT_SPEECH_RATIO = 0.05
SILENT_DBFS = -55.0
NOISY_SNR_DB = 10.0
CLIPPING_RATIO = 0.01


def _frame_energies(samples: array[int]) -> list[float]:
    n = SAMPLE_RATE * FRAME_MS // 1000
    try:
        import numpy as np

        arr = np.frombuffer(samples.tobytes(), dtype=np.int16).astype(np.float64)
        frames = len(arr) // n
        if frames == 0:
            return []
        sq = (arr[: frames * n] ** 2).reshape(frames, n).mean(axis=1)
        return [float(x) for x in np.sqrt(sq)]
    except ImportError:  # pragma: no cover - numpy is normally present
        out = []
        for i in range(0, len(samples) - n + 1, n):
            chunk = samples[i : i + n]
            out.append(math.sqrt(sum(s * s for s in chunk) / n))
        return out


def analyze_pcm16(pcm: bytes) -> AudioQuality:
    """Signal-quality report for 16 kHz mono PCM16 (deterministic)."""
    samples: array[int] = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    duration = len(samples) / SAMPLE_RATE
    if not samples:
        return AudioQuality(0.0, -120.0, 0.0, 0.0, 0.0, None, [], ["empty"])
    peak = max(abs(min(samples)), abs(max(samples))) / 32768.0
    clipped = sum(1 for s in samples if s >= 32700 or s <= -32700) / len(samples)
    energies = _frame_energies(samples)
    rms = math.sqrt(sum(e * e for e in energies) / len(energies)) if energies else 0.0
    rms_dbfs = 20 * math.log10(max(rms, 1e-9) / 32768.0)
    issues: list[str] = []
    snr_db: float | None = None
    speech_ratio = 0.0
    regions: list[tuple[float, float]] = []
    if energies:
        ordered = sorted(energies)
        noise = max(ordered[int(0.1 * (len(ordered) - 1))], 1.0)
        loud = max(ordered[int(0.9 * (len(ordered) - 1))], 1.0)
        snr_db = 20 * math.log10(loud / noise)
        floor = max(noise * 3.0, 300.0)  # 3x the noise floor, and audible
        voiced = [e > floor for e in energies]
        speech_ratio = sum(voiced) / len(voiced)
        step = FRAME_MS / 1000
        start: float | None = None
        for i, v in enumerate(voiced + [False]):
            if v and start is None:
                start = i * step
            elif not v and start is not None:
                if i * step - start >= 0.1:
                    regions.append((start, i * step))
                start = None
    if rms_dbfs < SILENT_DBFS:
        issues.append("no_speech_detected")  # (near-)silent recording
    elif snr_db is not None and snr_db < NOISY_SNR_DB:
        issues.append("noisy")  # loud, but speech (if any) is buried in noise
    elif speech_ratio < SILENT_SPEECH_RATIO:
        issues.append("no_speech_detected")
    if clipped > CLIPPING_RATIO:
        issues.append("clipped")
    return AudioQuality(duration, rms_dbfs, peak, clipped, speech_ratio, snr_db, regions, issues)


@dataclass
class IngestedAudio:
    asset: MediaAsset
    pcm16: bytes
    quality: AudioQuality

    def wav_bytes(self) -> bytes:
        """The decoded signal as a 16 kHz mono WAV (for processors that need a file)."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(self.pcm16)
        return buf.getvalue()


def ingest_audio(
    data: bytes,
    *,
    user_id: str,
    declared_format: str | None = None,
    language: str | None = None,
    limits: AudioLimits = DEFAULT_LIMITS,
) -> IngestedAudio:
    """Validate, decode and analyse a recording (see module docstring)."""
    if not data:
        raise AudioValidationError("empty", "no audio was received")
    if len(data) > limits.max_bytes:
        raise AudioValidationError(
            "too_large", f"audio exceeds {limits.max_bytes} bytes", http_status=413
        )
    sniffed = sniff_format(data)
    if sniffed is None:
        raise AudioValidationError(
            "unsupported_format",
            f"unrecognised audio format; supported: {', '.join(SUPPORTED_FORMATS)}",
            http_status=415,
        )
    declared = _normalize_declared(declared_format)
    if declared is not None and declared != sniffed:
        raise AudioValidationError(
            "format_mismatch", f"declared format {declared!r} but the data is {sniffed!r}"
        )
    pcm = decode_to_pcm16(data, sniffed, timeout_s=limits.decode_timeout_s)
    quality = analyze_pcm16(pcm)
    if quality.duration_s < limits.min_duration_s:
        raise AudioValidationError("too_short", f"audio is shorter than {limits.min_duration_s}s")
    if quality.duration_s > limits.max_duration_s:
        raise AudioValidationError(
            "too_long", f"audio is longer than {limits.max_duration_s}s", http_status=413
        )
    asset = MediaAsset(
        asset_id=uuid.uuid4().hex,
        user_id=user_id,
        modality=Modality.AUDIO,
        media_format=sniffed,
        sha256=sha256_hex(data),
        size_bytes=len(data),
        duration_s=round(quality.duration_s, 3),
        sample_rate=SAMPLE_RATE,
        channels=1,
        language=language,
    )
    logger.info(
        "audio ingested: format=%s bytes=%d duration=%.2fs issues=%s",
        sniffed, len(data), quality.duration_s, quality.issues,
    )  # fmt: skip
    return IngestedAudio(asset=asset, pcm16=pcm, quality=quality)
