"""Format support and edge cases (offline) — SYNTHETIC English speech.

The offline Windows voices (System.Speech) read a few English sentences. The
recordings are converted with ffmpeg to every supported container, then run
through the real ingestion and recogniser, which measures:

- **format support** — decode success per container;
- **latency** per container;
- **word error rate** per container (to check decoding is lossless enough).

Edge cases go through ingestion directly:

- silence, clipping, too short, too long;
- a truncated file;
- a declared format that does not match the data.

This runs only on Windows with System.Speech available.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from evals.speech.analysis import wer
from evals.speech.run import RESULTS
from src.multimodal.audio import AudioValidationError, ingest_audio
from src.multimodal.transcription import WhisperLocalProvider, run_transcription

OUT = Path(__file__).parent / "external" / "formats"
SENTENCES = (
    "The weather is lovely today, so we are going to the park.",
    "Could you tell me where the nearest train station is?",
)
VOICES = ("Microsoft Zira Desktop", "Microsoft Hazel Desktop")
CODECS = {
    "wav": [],
    "flac": [],
    "mp3": [],
    "ogg": ["-c:a", "libopus"],
    "webm": ["-c:a", "libopus"],
    "mp4": ["-c:a", "aac"],
}


def _sapi(text: str, voice: str, path: Path) -> None:
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SelectVoice('{voice}'); $s.SetOutputToWaveFile('{path}'); "
        f"$s.Speak('{text.replace(chr(39), '')}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)  # noqa: S603,S607


def _convert(src: Path, fmt: str) -> Path:
    dst = src.with_suffix(f".{fmt}") if fmt != "wav" else src.with_name(src.stem + "-pcm.wav")
    subprocess.run(  # noqa: S603,S607
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *CODECS[fmt], str(dst)], check=True
    )
    return dst


def _edge(name: str, data: bytes, declared: str | None = None) -> dict[str, Any]:
    try:
        r = ingest_audio(data, user_id="eval", declared_format=declared)
        return {"case": name, "accepted": True, "issues": r.quality.issues}
    except AudioValidationError as exc:
        return {"case": name, "accepted": False, "code": exc.code, "http_status": exc.http_status}


def run_formats() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    provider = WhisperLocalProvider("base")
    rows = []
    sources = []
    for i, (text, voice) in enumerate((s, v) for s in SENTENCES for v in VOICES):
        src = OUT / f"sapi-{i}.wav"
        if not src.exists():
            _sapi(text, voice, src)
        sources.append((src, text, voice))
    for src, text, voice in sources:
        for fmt in CODECS:
            path = _convert(src, fmt)
            data = path.read_bytes()
            t0 = time.perf_counter()
            row: dict[str, Any] = {"format": fmt, "voice": voice, "bytes": len(data)}
            try:
                ing = ingest_audio(data, user_id="eval", declared_format=fmt, language="English")
                obs, step = run_transcription(
                    provider, ing.asset.asset_id, ing.wav_bytes(), language="English"
                )
                row["decoded"] = True
                row["duration_s"] = ing.quality.duration_s
                if obs is not None:
                    e, n = wer(text, obs.data["transcript"].text)
                    row["wer"] = e / n
            except AudioValidationError as exc:
                row["decoded"] = False
                row["code"] = exc.code
            row["latency_ms"] = (time.perf_counter() - t0) * 1000
            rows.append(row)
    base = sources[0][0].read_bytes()
    pcm = base[44:]
    import numpy as np

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    loud = np.clip(x * 20, -32768, 32767).astype(np.int16).tobytes()
    header = base[:44]

    def as_wav(payload: bytes) -> bytes:
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(io.BytesIO(base)) as src_w, wave.open(buf, "wb") as w:
            w.setnchannels(src_w.getnchannels())
            w.setsampwidth(2)
            w.setframerate(src_w.getframerate())
            w.writeframes(payload)
        return buf.getvalue()

    rate_bytes = int.from_bytes(header[28:32], "little")
    webm = (OUT / "sapi-0.webm").read_bytes()
    edges = [
        _edge("silence", as_wav(b"\x00\x00" * (rate_bytes // 2) * 3)),
        _edge("clipped", as_wav(loud)),
        _edge("too_short", as_wav(pcm[: rate_bytes // 10])),
        _edge("too_long", as_wav(pcm * (int(130 / max(len(pcm) / rate_bytes, 0.1)) + 1))),
        _edge("truncated_webm", webm[: len(webm) // 8], "webm"),
        _edge("mislabelled", base, "mp3"),
        _edge("not_audio", b"%PDF-1.4 definitely not audio" * 10),
    ]
    by_format: dict[str, dict[str, Any]] = {}
    for fmt in CODECS:
        rs = [r for r in rows if r["format"] == fmt]
        lat = sorted(r["latency_ms"] for r in rs)
        wers = [r["wer"] for r in rs if "wer" in r]
        by_format[fmt] = {
            "clips": len(rs),
            "decoded": sum(1 for r in rs if r["decoded"]),
            "latency_ms_median": lat[len(lat) // 2] if lat else None,
            "mean_wer": sum(wers) / len(wers) if wers else None,
        }
    result = {"data": "synthetic_offline_tts", "by_format": by_format, "edge_cases": edges}
    (RESULTS / "formats.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
