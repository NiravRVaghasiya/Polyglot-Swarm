"""Synthetic Spanish speech (Edge TTS) — SYNTHETIC, not learner speech.

Native-quality synthetic voices read sentences from the Phase 2 grammar
dataset: correct sentences, and sentences with one known learner error. The
synthetic voices pronounce every word correctly, so this set measures the
*recogniser and the pipeline*, not learners:

- transcription accuracy by accent, rate and noise;
- false "not intelligible" flags on correctly pronounced speech in each
  regional accent, which is the accent-fairness check;
- whether the recogniser preserves a learner's grammar error or silently
  "corrects" it, i.e. the risk to spoken-grammar evidence;
- abstention on silence and on noise-only clips.

It carries no expert labels and says nothing about pronunciation quality.

The audio is generated once into ``evals/speech/external/synthetic/``
(git-ignored), together with a manifest.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import random
import subprocess
import wave
from pathlib import Path
from typing import Any

import yaml

OUT = Path(__file__).parent / "external" / "synthetic"
GRAMMAR_SOURCE = Path(__file__).parents[1] / "real" / "datasets" / "grammar" / "source.yaml"
VOICES = {
    "es-ES-AlvaroNeural": "Spain",
    "es-ES-ElviraNeural": "Spain",
    "es-MX-JorgeNeural": "Mexico",
    "es-MX-DaliaNeural": "Mexico",
    "es-AR-ElenaNeural": "Argentina",
    "es-CO-GonzaloNeural": "Colombia",
}
RATES = ("+0%", "+25%")
NOISE_VOICES = ("es-ES-AlvaroNeural", "es-MX-DaliaNeural")
SNRS_DB = (20, 10, 0)
N_PER_CATEGORY = 12


def sentences() -> list[dict[str, Any]]:
    data = yaml.safe_load(GRAMMAR_SOURCE.read_text(encoding="utf-8"))
    es = [c for c in data["cases"] if c["lang"] == "Spanish"]
    correct = [c for c in es if c["cat"] == "correct"][:N_PER_CATEGORY]
    incorrect = [c for c in es if c["cat"] == "incorrect" and len(c.get("errors") or []) == 1][
        :N_PER_CATEGORY
    ]
    return [
        {
            "case_id": c["id"],
            "text": c["text"],
            "category": c["cat"],
            "error_span": (c.get("errors") or [{}])[0].get("span"),
            "fixes": (c.get("errors") or [{}])[0].get("fix", []),
        }
        for c in correct + incorrect
    ]


def _to_pcm16(mp3: bytes) -> bytes:
    proc = subprocess.run(  # noqa: S603 - fixed argv
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-ac", "1",
         "-ar", "16000", "-f", "s16le", "pipe:1"],
        input=mp3, capture_output=True, check=True,
    )  # fmt: skip
    return proc.stdout


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


def _mix_noise(pcm: bytes, snr_db: float, seed: int) -> bytes:
    import numpy as np

    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    power = float(np.mean(x**2)) or 1.0
    noise_power = power / (10 ** (snr_db / 10))
    rng = np.random.default_rng(seed)
    y = x + rng.normal(0.0, math.sqrt(noise_power), size=x.shape)
    return np.clip(y, -32768, 32767).astype(np.int16).tobytes()


async def _tts(text: str, voice: str, rate: str) -> bytes:
    import edge_tts  # type: ignore[import-not-found, import-untyped, unused-ignore]

    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            audio.extend(chunk["data"])
    return bytes(audio)


async def build() -> Path:
    """Generate (or complete) the synthetic set; returns the manifest path."""
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    clips: list[dict[str, Any]] = []
    for s in sentences():
        for voice, accent in VOICES.items():
            for rate in RATES:
                cid = f"syn-{s['case_id']}-{voice}-{rate.replace('%', '').replace('+', 'p')}"
                path = OUT / f"{cid}.wav"
                if not path.exists():
                    pcm = _to_pcm16(await _tts(s["text"], voice, rate))
                    path.write_bytes(_wav(pcm))
                base = {**s, "voice": voice, "accent": accent, "rate": rate, "language": "Spanish"}
                clips.append({**base, "clip_id": cid, "path": str(path), "snr_db": None})
                if voice in NOISE_VOICES and rate == "+0%":
                    clean = path.read_bytes()[44:]
                    for snr in SNRS_DB:
                        nid = f"{cid}-snr{snr}"
                        npath = OUT / f"{nid}.wav"
                        if not npath.exists():
                            npath.write_bytes(_wav(_mix_noise(clean, snr, hash(nid) & 0xFFFF)))
                        clips.append({**base, "clip_id": nid, "path": str(npath), "snr_db": snr})
    rng = random.Random(7)
    for i in range(4):
        sil = OUT / f"syn-silence-{i}.wav"
        noi = OUT / f"syn-noiseonly-{i}.wav"
        n = 16000 * 3
        if not sil.exists():
            sil.write_bytes(
                _wav(
                    b"".join(
                        int(rng.gauss(0, 15)).to_bytes(2, "little", signed=True) for _ in range(n)
                    )
                )
            )
        if not noi.exists():
            noi.write_bytes(
                _wav(
                    b"".join(
                        int(max(-32768, min(32767, rng.gauss(0, 3000)))).to_bytes(
                            2, "little", signed=True
                        )
                        for _ in range(n)
                    )
                )
            )
        for kind, p in (("silence", sil), ("noise_only", noi)):
            clips.append(
                {"clip_id": p.stem, "path": str(p), "category": kind, "text": "",
                 "language": "Spanish", "voice": None, "accent": None, "rate": None, "snr_db": None}
            )  # fmt: skip
    manifest_path.write_text(
        json.dumps({"synthetic": True, "clips": clips}, indent=1), encoding="utf-8"
    )
    return manifest_path


def manifest() -> list[dict[str, Any]]:
    data = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    return list(data["clips"])


if __name__ == "__main__":
    print(asyncio.run(build()))
