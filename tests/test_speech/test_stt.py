"""Tests for the Whisper STT module (Whisper mocked — no torch needed)."""

from __future__ import annotations

import sys
import types

import pytest

from src.speech import stt
from src.speech.stt import SpeechDependencyError, language_to_whisper_code


class TestLanguageMapping:
    @pytest.mark.parametrize(
        "name,code",
        [("Spanish", "es"), ("polish", "pl"), ("Italian", "it"),
         ("es", "es"), ("English", "en")],
    )
    def test_maps(self, name, code):
        assert language_to_whisper_code(name) == code

    def test_none(self):
        assert language_to_whisper_code(None) is None

    def test_unknown_long_name(self):
        assert language_to_whisper_code("Klingon") is None


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path, language=None):
        self.calls.append({"audio": audio_path, "language": language})
        return {"text": "  hola mundo  "}


@pytest.fixture
def fake_whisper(monkeypatch):
    stt._load_model.cache_clear()
    model = _FakeModel()
    module = types.ModuleType("whisper")
    module.load_model = lambda size: model
    monkeypatch.setitem(sys.modules, "whisper", module)
    yield model
    stt._load_model.cache_clear()


class TestTranscribe:
    def test_transcribes_and_strips(self, fake_whisper):
        text = stt.transcribe("clip.wav", language="Spanish")
        assert text == "hola mundo"

    def test_passes_language_code(self, fake_whisper):
        stt.transcribe("clip.wav", language="Italian")
        assert fake_whisper.calls[0]["language"] == "it"

    def test_no_language_hint(self, fake_whisper):
        stt.transcribe("clip.wav")
        assert fake_whisper.calls[0]["language"] is None


class TestMissingDependency:
    def test_raises_clear_error(self, monkeypatch):
        stt._load_model.cache_clear()

        # Simulate whisper not installed.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "whisper":
                raise ImportError("no whisper")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(SpeechDependencyError, match="voice extra"):
            stt.transcribe("clip.wav")
        stt._load_model.cache_clear()
