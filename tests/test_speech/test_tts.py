"""Tests for the Edge TTS module (edge_tts mocked — no network)."""

from __future__ import annotations

import sys
import types

import pytest

from src.speech import tts
from src.speech.stt import SpeechDependencyError
from src.speech.tts import DEFAULT_VOICE, voice_for_language


class TestVoiceMapping:
    @pytest.mark.parametrize(
        "name,voice",
        [
            ("Spanish", "es-ES-AlvaroNeural"),
            ("polish", "pl-PL-MarekNeural"),
            ("Italian", "it-IT-DiegoNeural"),
        ],
    )
    def test_maps(self, name, voice):
        assert voice_for_language(name) == voice

    def test_unknown_falls_back(self):
        assert voice_for_language("Klingon") == DEFAULT_VOICE

    def test_none_falls_back(self):
        assert voice_for_language(None) == DEFAULT_VOICE


class _FakeCommunicate:
    last: _FakeCommunicate | None = None

    def __init__(self, text, voice):
        self.text = text
        self.voice = voice
        self.saved_to = None
        type(self).last = self

    async def stream(self):
        # Emit two audio chunks and a non-audio chunk to be filtered out.
        yield {"type": "audio", "data": b"AB"}
        yield {"type": "WordBoundary", "data": None}
        yield {"type": "audio", "data": b"CD"}

    async def save(self, path):
        self.saved_to = path


@pytest.fixture
def fake_edge_tts(monkeypatch):
    module = types.ModuleType("edge_tts")
    module.Communicate = _FakeCommunicate
    monkeypatch.setitem(sys.modules, "edge_tts", module)
    return _FakeCommunicate


class TestSynthesize:
    async def test_returns_concatenated_audio(self, fake_edge_tts):
        audio = await tts.synthesize("hola", language="Spanish")
        assert audio == b"ABCD"

    async def test_uses_language_voice(self, fake_edge_tts):
        await tts.synthesize("ciao", language="Italian")
        assert fake_edge_tts.last.voice == "it-IT-DiegoNeural"

    async def test_explicit_voice_overrides(self, fake_edge_tts):
        await tts.synthesize("hi", language="Spanish", voice="custom-Voice")
        assert fake_edge_tts.last.voice == "custom-Voice"

    async def test_empty_text_returns_empty(self, fake_edge_tts):
        assert await tts.synthesize("   ") == b""

    async def test_to_file(self, fake_edge_tts, tmp_path):
        out = str(tmp_path / "out.mp3")
        result = await tts.synthesize_to_file("hola", out, language="Spanish")
        assert result == out
        assert fake_edge_tts.last.saved_to == out


class TestMissingDependency:
    async def test_raises_clear_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "edge_tts":
                raise ImportError("no edge_tts")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(SpeechDependencyError, match="voice extra"):
            await tts.synthesize("hola", language="Spanish")
