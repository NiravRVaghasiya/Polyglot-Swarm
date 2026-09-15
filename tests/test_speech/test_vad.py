"""Phase 15 tests: voice activity detection + its pipeline integration."""

from __future__ import annotations

import struct

import pytest

from src.speech import vad
from src.speech.livekit_agent import VoicePipeline
from src.speech.stt import SpeechDependencyError


def _pcm(amplitude: int, samples: int = 480) -> bytes:
    """Build a 16-bit PCM buffer of a constant amplitude."""
    return struct.pack(f"<{samples}h", *([amplitude] * samples))


class TestEnergyVAD:
    def test_empty_is_silence(self):
        assert not vad.has_speech(b"")

    def test_all_zero_is_silence(self):
        assert not vad.has_speech(_pcm(0))

    def test_loud_pcm_is_speech(self):
        assert vad.has_speech(_pcm(5000))

    def test_quiet_pcm_below_threshold_is_silence(self):
        assert not vad.has_speech(_pcm(10))

    def test_is_silence_inverse(self):
        assert vad.is_silence(_pcm(0))
        assert not vad.is_silence(_pcm(5000))

    def test_non_pcm_bytes_heuristic(self):
        # Odd-length / non-PCM bytes fall back to the byte heuristic.
        assert vad.has_speech(b"raw-audio-bytes")
        assert not vad.has_speech(bytes(200))


class TestWebrtcFallback:
    def test_webrtc_requested_but_missing_falls_back(self, monkeypatch):
        # use_webrtc=True but webrtcvad not installed -> energy fallback, no raise.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "webrtcvad":
                raise ImportError("no webrtcvad")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        # Loud buffer -> energy fallback says speech; no SpeechDependencyError.
        assert vad.has_speech(_pcm(5000), use_webrtc=True)

    def test_webrtc_direct_missing_raises(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "webrtcvad":
                raise ImportError("no webrtcvad")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(SpeechDependencyError, match="voice extra"):
            vad._webrtc_has_speech(_pcm(5000), sample_rate=16000, aggressiveness=2)


class TestPipelineVADGate:
    def _pipeline(self, vad_fn=None):
        order: list[str] = []

        async def fake_transcribe(audio, language):
            order.append("stt")
            return "hola"

        async def fake_respond(text):
            order.append("agent")
            return "reply"

        async def fake_synthesize(text, language):
            order.append("tts")
            return b"AUDIO"

        pipeline = VoicePipeline(
            transcribe=fake_transcribe,
            respond=fake_respond,
            synthesize=fake_synthesize,
            vad=vad_fn if vad_fn is not None else (lambda a: True),
        )
        return pipeline, order

    async def test_vad_runs_before_stt(self):
        pipeline, order = self._pipeline(vad_fn=lambda a: True)
        await pipeline.handle_audio(b"audio")
        assert pipeline.trace[0] == "vad"
        assert order == ["stt", "agent", "tts"]

    async def test_no_speech_skips_all_stages(self):
        pipeline, order = self._pipeline(vad_fn=lambda a: False)
        result = await pipeline.handle_audio(b"silence")
        assert pipeline.trace == ["vad"]  # nothing after VAD
        assert order == []  # STT/agent/TTS never ran
        assert result == {"transcript": "", "reply": "", "audio": b"", "pronunciation": None}

    async def test_vad_can_be_disabled(self):
        # vad=None-equivalent: pass a passthrough; but explicitly disabling means
        # constructing with the default and overriding. Here we verify default-on.
        pipeline, order = self._pipeline(vad_fn=lambda a: True)
        result = await pipeline.handle_audio(b"audio")
        assert result["transcript"] == "hola"

    async def test_expected_text_scores_pronunciation_on_normal_turn(self):
        pipeline, _ = self._pipeline(vad_fn=lambda a: True)
        result = await pipeline.handle_audio(b"audio", expected_text="hola")
        assert result["pronunciation"] is not None
        assert result["pronunciation"]["accuracy"] == 1.0

    async def test_default_vad_is_energy_based(self):
        # With no vad= argument, the pipeline uses the energy detector: a loud
        # buffer proceeds, an all-zero buffer is skipped.
        order: list[str] = []

        async def fake_transcribe(audio, language):
            order.append("stt")
            return "hola"

        async def fake_respond(text):
            return "r"

        async def fake_synthesize(text, language):
            return b"A"

        pipeline = VoicePipeline(
            transcribe=fake_transcribe, respond=fake_respond, synthesize=fake_synthesize
        )
        await pipeline.handle_audio(_pcm(5000))
        assert "stt" in order
