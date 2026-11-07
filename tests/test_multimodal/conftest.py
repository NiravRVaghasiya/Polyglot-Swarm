"""Fixtures for multimodal tests: synthetic signals and a scripted recogniser.

The synthetic signals are deterministic test fixtures, not speech. They
exercise ingestion, quality analysis and the pipeline's control flow. Real
recognition is covered by the opt-in test and by evals/speech.
"""

from __future__ import annotations

import io
import math
import random
import wave
from typing import Any

import pytest

from src.config import settings
from src.multimodal.transcription import Segment, Transcript, TranscriptionError, Word
from tests.test_api.conftest import auth_client, client  # noqa: F401 - shared fixtures

SR = 16_000


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


def wav(samples: list[int], sr: int = SR, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(
            b"".join(
                int(max(-32768, min(32767, s))).to_bytes(2, "little", signed=True) for s in samples
            )
        )
    return buf.getvalue()


def speech_like(
    seconds: float = 2.0, *, noise: float = 0.0, amp: float = 8000, seed: int = 1
) -> list[int]:
    """Bursts of a modulated tone (voiced-like regions) separated by gaps."""
    rng = random.Random(seed)
    out = []
    for i in range(int(seconds * SR)):
        t = i / SR
        burst = 1.0 if (t % 0.5) < 0.35 else 0.0
        s = (
            burst
            * amp
            * math.sin(2 * math.pi * 180 * t)
            * (0.6 + 0.4 * math.sin(2 * math.pi * 3 * t))
        )
        s += rng.gauss(0, noise) if noise else 0.0
        out.append(int(s))
    return out


def silence(seconds: float = 2.0, *, noise: float = 20.0, seed: int = 2) -> list[int]:
    rng = random.Random(seed)
    return [int(rng.gauss(0, noise)) for _ in range(int(seconds * SR))]


def make_transcript(
    text: str,
    *,
    gaps: list[float] | None = None,
    prob: float = 0.9,
    language: str = "es",
    language_probability: float = 0.99,
    word_s: float = 0.3,
) -> Transcript:
    words, t = [], 0.2
    for i, token in enumerate(text.split()):
        words.append(Word(token, t, t + word_s, prob))
        t += word_s + (gaps[i] if gaps and i < len(gaps) else 0.05)
    return Transcript(
        text=text,
        language=language,
        language_probability=language_probability,
        segments=[Segment(words[0].start, words[-1].end, text, -0.2, 0.01, words)] if words else [],
        provider="scripted",
        model="scripted-1",
    )


class ScriptedSTT:
    """A recogniser stand-in returning a fixed transcript (or failing)."""

    name = "scripted"
    model = "scripted-1"

    def __init__(
        self,
        transcript: Transcript | None = None,
        *,
        fail: str | None = None,
        fail_times: int = 0,
        available: bool = True,
    ) -> None:
        self.transcript = transcript
        self.fail = fail
        self.fail_times = fail_times
        self._available = available
        self.calls = 0

    def available(self) -> bool:
        return self._available

    def transcribe(self, wav_bytes: bytes, *, language: str | None) -> Transcript:
        self.calls += 1
        if self.fail and (self.fail_times == 0 or self.calls <= self.fail_times):
            raise TranscriptionError(self.fail, "scripted failure")
        assert self.transcript is not None
        return self.transcript


def scripted(**kw: Any) -> ScriptedSTT:
    return ScriptedSTT(**kw)
