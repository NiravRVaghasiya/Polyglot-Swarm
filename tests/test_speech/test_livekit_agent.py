"""Tests for the voice pipeline and LiveKit transport (all mocked)."""

from __future__ import annotations

import sys
import types

import pytest

from src.speech.livekit_agent import LiveKitVoiceAgent, VoicePipeline
from src.speech.stt import SpeechDependencyError


def _make_pipeline(*, transcript="hola mesa", reply="¡Bienvenido!"):
    order: list[str] = []

    async def fake_transcribe(audio, language):
        order.append("stt")
        return transcript

    async def fake_respond(text):
        order.append("agent")
        assert "stt" in order  # agent runs after STT
        return reply

    async def fake_synthesize(text, language):
        order.append("tts")
        assert "agent" in order  # TTS runs after the agent
        return b"AUDIO:" + text.encode("utf-8")

    pipeline = VoicePipeline(
        language="Spanish",
        transcribe=fake_transcribe,
        respond=fake_respond,
        synthesize=fake_synthesize,
    )
    return pipeline, order


class TestVoicePipeline:
    async def test_runs_stt_agent_tts_in_order(self):
        pipeline, order = _make_pipeline()
        result = await pipeline.handle_audio(b"raw-audio")

        assert order == ["stt", "agent", "tts"]
        assert pipeline.trace == ["stt", "agent", "tts"]
        assert result["transcript"] == "hola mesa"
        assert result["reply"] == "¡Bienvenido!"
        assert result["audio"].startswith(b"AUDIO:")

    async def test_silence_skips_agent(self):
        pipeline, order = _make_pipeline(transcript="   ")
        result = await pipeline.handle_audio(b"silence")
        assert order == ["stt"]  # agent + tts never ran
        assert result["reply"] == ""
        assert result["audio"] == b""

    async def test_scripted_scores_pronunciation(self):
        pipeline, _ = _make_pipeline(transcript="una mesa", reply="ok")
        result = await pipeline.handle_scripted_audio(b"audio", target_text="una mesa")
        assert result["pronunciation"]["accuracy"] == 1.0

    async def test_scripted_flags_mispronunciation(self):
        pipeline, _ = _make_pipeline(transcript="una xyz", reply="ok")
        result = await pipeline.handle_scripted_audio(b"audio", target_text="una mesa")
        assert "mesa" in result["pronunciation"]["problem_words"]


class _FakeRoom:
    def __init__(self):
        self.connected_to = None
        self.disconnected = False

    async def connect(self, url, token):
        self.connected_to = (url, token)

    async def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_livekit(monkeypatch):
    room = _FakeRoom()
    rtc = types.SimpleNamespace(Room=lambda: room)
    module = types.ModuleType("livekit")
    module.rtc = rtc
    monkeypatch.setitem(sys.modules, "livekit", module)
    return room


class TestLiveKitAgent:
    async def test_connect_and_disconnect(self, fake_livekit):
        pipeline, _ = _make_pipeline()
        agent = LiveKitVoiceAgent(pipeline)

        room = await agent.connect("wss://room", "token123")
        assert room.connected_to == ("wss://room", "token123")

        await agent.disconnect()
        assert fake_livekit.disconnected is True

    async def test_on_utterance_returns_audio(self, fake_livekit):
        pipeline, order = _make_pipeline()
        agent = LiveKitVoiceAgent(pipeline)
        audio = await agent.on_utterance(b"raw")
        assert audio.startswith(b"AUDIO:")
        assert order == ["stt", "agent", "tts"]

    async def test_missing_livekit_raises(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "livekit":
                raise ImportError("no livekit")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        pipeline, _ = _make_pipeline()
        agent = LiveKitVoiceAgent(pipeline)
        with pytest.raises(SpeechDependencyError, match="voice extra"):
            await agent.connect("wss://x", "t")
