"""Tests for the voice API routes (Gate E: voice in the web frontend).

The endpoints carry audio as base64 JSON (no multipart dependency). They are
auth-scoped and degrade gracefully to 503 when the optional speech extra is
not installed. Success paths are exercised by patching the STT/TTS functions.
"""

from __future__ import annotations

import base64

from src.speech.stt import SpeechDependencyError


class TestTranscribe:
    def test_requires_auth(self, client):
        resp = client.post("/api/v1/voice/transcribe", json={"audio_base64": ""})
        assert resp.status_code == 401

    def test_empty_audio_returns_empty_transcript(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post("/api/v1/voice/transcribe", json={"audio_base64": ""}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["transcript"] == ""

    def test_invalid_base64_is_400(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post(
            "/api/v1/voice/transcribe",
            json={"audio_base64": "!!!not base64!!!"},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_success_path_returns_transcript(self, auth_client, monkeypatch):
        client, headers, _ = auth_client
        # Patch the STT function the route imports.
        import src.speech.stt as stt

        monkeypatch.setattr(stt, "transcribe", lambda path, language=None: "hola mundo")

        audio = base64.b64encode(b"fake-audio-bytes").decode("ascii")
        resp = client.post(
            "/api/v1/voice/transcribe",
            json={"audio_base64": audio, "audio_format": "webm", "language": "Spanish"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["transcript"] == "hola mundo"

    def test_missing_voice_extra_is_503(self, auth_client, monkeypatch):
        client, headers, _ = auth_client
        import src.speech.stt as stt

        def boom(path, language=None):
            raise SpeechDependencyError("Whisper is not installed. voice extra")

        monkeypatch.setattr(stt, "transcribe", boom)
        audio = base64.b64encode(b"fake-audio").decode("ascii")
        resp = client.post(
            "/api/v1/voice/transcribe", json={"audio_base64": audio}, headers=headers
        )
        assert resp.status_code == 503
        assert "voice extra" in resp.json()["detail"]


class TestSpeak:
    def test_requires_auth(self, client):
        resp = client.post("/api/v1/voice/speak", json={"text": "hola"})
        assert resp.status_code == 401

    def test_empty_text_returns_empty_audio(self, auth_client):
        client, headers, _ = auth_client
        resp = client.post("/api/v1/voice/speak", json={"text": "   "}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["audio_base64"] == ""

    def test_success_path_returns_base64_audio(self, auth_client, monkeypatch):
        client, headers, _ = auth_client
        import src.speech.tts as tts

        async def fake_synth(text, *, language=None, voice=None):
            return b"MP3_AUDIO_BYTES"

        monkeypatch.setattr(tts, "synthesize", fake_synth)
        resp = client.post(
            "/api/v1/voice/speak",
            json={"text": "hola", "language": "Spanish"},
            headers=headers,
        )
        assert resp.status_code == 200
        decoded = base64.b64decode(resp.json()["audio_base64"])
        assert decoded == b"MP3_AUDIO_BYTES"

    def test_missing_voice_extra_is_503(self, auth_client, monkeypatch):
        client, headers, _ = auth_client
        import src.speech.tts as tts

        async def boom(text, *, language=None, voice=None):
            raise SpeechDependencyError("edge-tts is not installed. voice extra")

        monkeypatch.setattr(tts, "synthesize", boom)
        resp = client.post("/api/v1/voice/speak", json={"text": "hola"}, headers=headers)
        assert resp.status_code == 503
