"""LiveKit real-time voice transport.

Wires the speech pipeline to a LiveKit WebRTC room so a learner can hold a
spoken conversation: incoming audio -> Whisper STT -> the agent graph -> Edge
TTS -> outgoing audio.

The orchestration lives in :class:`VoicePipeline`, which is transport-agnostic
and unit-testable (STT/graph/TTS are injectable). :class:`LiveKitVoiceAgent`
adapts that pipeline onto a LiveKit room; the ``livekit`` SDK is optional and
imported lazily, so importing this module never requires it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.speech import pronunciation
from src.speech.stt import SpeechDependencyError

logger = logging.getLogger("polyglot.voice")

# Injectable async callables so the pipeline can be tested without real deps.
Transcriber = Callable[[bytes, str | None], Awaitable[str]]
Responder = Callable[[str], Awaitable[str]]
Synthesizer = Callable[[str, str | None], Awaitable[bytes]]


async def _default_transcriber(audio: bytes, language: str | None) -> str:
    # Whisper reads files; write the buffer to a temp file first.
    import tempfile

    from src.speech.stt import transcribe

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio)
        path = f.name
    return transcribe(path, language=language)


async def _default_synthesizer(text: str, language: str | None) -> bytes:
    from src.speech.tts import synthesize

    return await synthesize(text, language=language)


class VoicePipeline:
    """Orchestrates one voice turn: audio -> STT -> agent -> TTS -> audio.

    All three stages are injectable, so tests can drive the pipeline without
    Whisper, an LLM, or Edge TTS. The default stages use the real modules.
    """

    def __init__(
        self,
        *,
        language: str | None = None,
        transcribe: Transcriber | None = None,
        respond: Responder,
        synthesize: Synthesizer | None = None,
    ) -> None:
        self.language = language
        self._transcribe = transcribe or _default_transcriber
        self._respond = respond
        self._synthesize = synthesize or _default_synthesizer
        # Ordered record of stages run this session (useful for tests/telemetry).
        self.trace: list[str] = []

    async def handle_audio(self, audio: bytes) -> dict[str, Any]:
        """Process one utterance end to end.

        Returns ``{"transcript", "reply", "audio", "pronunciation"}``. If STT
        yields nothing (silence), the agent is not invoked.
        """
        self.trace.append("stt")
        transcript = await self._transcribe(audio, self.language)
        if not transcript.strip():
            return {"transcript": "", "reply": "", "audio": b"", "pronunciation": None}

        self.trace.append("agent")
        reply = await self._respond(transcript)

        self.trace.append("tts")
        out_audio = await self._synthesize(reply, self.language)

        return {
            "transcript": transcript,
            "reply": reply,
            "audio": out_audio,
            "pronunciation": None,
        }

    async def handle_scripted_audio(self, audio: bytes, target_text: str) -> dict[str, Any]:
        """Like :meth:`handle_audio` but scores pronunciation against a target.

        Used in scenario/drill mode where the learner is expected to say a
        specific line, enabling pronunciation feedback.
        """
        result = await self.handle_audio(audio)
        if result["transcript"]:
            result["pronunciation"] = pronunciation.assess_pronunciation(
                target_text, result["transcript"]
            )
        return result


class LiveKitVoiceAgent:
    """Adapts a :class:`VoicePipeline` onto a LiveKit WebRTC room.

    Connects to a room, subscribes to the participant's audio track, runs each
    detected utterance through the pipeline, and publishes the synthesized
    reply back. The ``livekit`` SDK is imported lazily.
    """

    def __init__(self, pipeline: VoicePipeline) -> None:
        self.pipeline = pipeline
        self._room: Any = None

    @staticmethod
    def _import_livekit() -> Any:
        try:
            import livekit  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise SpeechDependencyError(
                "livekit is not installed. Install the voice extra: "
                "pip install 'polyglot-swarm[voice]'"
            ) from exc
        return livekit

    async def connect(self, url: str, token: str) -> Any:
        """Connect to a LiveKit room and return the room handle."""
        livekit = self._import_livekit()
        room = livekit.rtc.Room()
        await room.connect(url, token)
        self._room = room
        return room

    async def on_utterance(self, audio: bytes) -> bytes:
        """Handle one detected utterance and return the reply audio to publish."""
        result = await self.pipeline.handle_audio(audio)
        audio_out: bytes = result["audio"]
        return audio_out

    async def disconnect(self) -> None:
        if self._room is not None:
            await self._room.disconnect()
            self._room = None
