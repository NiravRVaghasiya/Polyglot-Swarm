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
# VAD is synchronous (cheap, no I/O): audio -> has-speech.
VoiceDetector = Callable[[bytes], bool]


def _default_vad(audio: bytes) -> bool:
    """Default VAD: the dependency-free energy detector from :mod:`src.speech.vad`."""
    from src.speech.vad import has_speech

    return has_speech(audio)


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

    # Phase 23: TTS is an optional dependency (edge-tts) and a network call;
    # either can be unavailable in a given deployment/moment. A voice turn
    # should not be lost entirely just because audio couldn't be produced —
    # fall back to text-only (empty audio) so the transcript/reply still
    # reach the caller, rather than letting SpeechDependencyError (or a
    # transient edge-tts failure) propagate out of the whole pipeline.
    try:
        return await synthesize(text, language=language)
    except SpeechDependencyError as exc:
        logger.warning("TTS unavailable, falling back to text-only: %s", exc)
        return b""
    except Exception as exc:  # noqa: BLE001 - a TTS outage must not lose the turn
        logger.error("TTS synthesis failed, falling back to text-only: %s", exc)
        return b""


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
        vad: VoiceDetector | None = None,
    ) -> None:
        self.language = language
        self._transcribe = transcribe or _default_transcriber
        self._respond = respond
        self._synthesize = synthesize or _default_synthesizer
        # VAD gate: skip STT/agent/TTS on silence. Defaults to the dependency
        # -free energy detector; injectable for tests / webrtcvad. Set to None
        # explicitly to disable the VAD stage entirely.
        self._vad: VoiceDetector | None = vad if vad is not None else _default_vad
        # Ordered record of stages run this session (useful for tests/telemetry).
        self.trace: list[str] = []

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {"transcript": "", "reply": "", "audio": b"", "pronunciation": None}

    async def handle_audio(
        self, audio: bytes, *, expected_text: str | None = None
    ) -> dict[str, Any]:
        """Process one utterance end to end.

        Returns ``{"transcript", "reply", "audio", "pronunciation"}``. A VAD
        stage runs first (Phase 15): if the buffer contains no speech, the
        expensive STT/agent/TTS stages are skipped. STT yielding nothing
        (silence heard as empty text) also short-circuits before the agent.

        When ``expected_text`` is given, pronunciation is scored against it even
        on a normal turn (not only scripted mode).
        """
        # --- VAD: skip everything on silence. ---
        if self._vad is not None:
            self.trace.append("vad")
            if not self._vad(audio):
                return self._empty_result()

        self.trace.append("stt")
        transcript = await self._transcribe(audio, self.language)
        if not transcript.strip():
            return self._empty_result()

        self.trace.append("agent")
        reply = await self._respond(transcript)

        self.trace.append("tts")
        out_audio = await self._synthesize(reply, self.language)

        pron = (
            pronunciation.assess_pronunciation(expected_text, transcript) if expected_text else None
        )
        return {
            "transcript": transcript,
            "reply": reply,
            "audio": out_audio,
            "pronunciation": pron,
        }

    async def handle_scripted_audio(self, audio: bytes, target_text: str) -> dict[str, Any]:
        """Like :meth:`handle_audio` but scores pronunciation against a target.

        Used in scenario/drill mode where the learner is expected to say a
        specific line, enabling pronunciation feedback.
        """
        return await self.handle_audio(audio, expected_text=target_text)


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
