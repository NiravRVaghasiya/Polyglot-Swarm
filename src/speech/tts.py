"""Text-to-speech via Edge TTS.

Synthesizes agent replies to audio using Microsoft Edge's free TTS voices, with
a per-language voice map. ``edge_tts`` is an optional dependency (the ``voice``
extra) and is imported lazily, so importing this module never requires it; a
clear :class:`SpeechDependencyError` is raised at call time if it is missing.
"""

from __future__ import annotations

from typing import Any

from src.speech.stt import SpeechDependencyError

# Free-form language name (lowercased) -> Edge TTS voice.
_LANG_TO_VOICE = {
    "spanish": "es-ES-AlvaroNeural",
    "polish": "pl-PL-MarekNeural",
    "italian": "it-IT-DiegoNeural",
    "english": "en-US-GuyNeural",
}

DEFAULT_VOICE = "en-US-GuyNeural"


def voice_for_language(language: str | None) -> str:
    """Return the Edge TTS voice for a language name, falling back to a default."""
    if not language:
        return DEFAULT_VOICE
    return _LANG_TO_VOICE.get(language.strip().lower(), DEFAULT_VOICE)


def _communicate(text: str, voice: str) -> Any:
    """Build an edge_tts.Communicate, raising a clear error if unavailable."""
    try:
        import edge_tts  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SpeechDependencyError(
            "edge-tts is not installed. Install the voice extra: "
            "pip install 'polyglot-swarm[voice]'"
        ) from exc
    return edge_tts.Communicate(text, voice)


async def synthesize(text: str, *, language: str | None = None, voice: str | None = None) -> bytes:
    """Synthesize ``text`` to speech and return the audio as MP3 bytes.

    Args:
        text: The text to speak.
        language: Free-form language name used to pick a default voice.
        voice: An explicit Edge TTS voice name (overrides ``language``).

    Returns:
        The synthesized audio as bytes (empty for empty input).
    """
    if not text.strip():
        return b""

    chosen_voice = voice or voice_for_language(language)
    communicate = _communicate(text, chosen_voice)

    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            audio.extend(chunk["data"])
    return bytes(audio)


async def synthesize_to_file(
    text: str, path: str, *, language: str | None = None, voice: str | None = None
) -> str:
    """Synthesize ``text`` to speech and write it to ``path``. Returns the path."""
    chosen_voice = voice or voice_for_language(language)
    communicate = _communicate(text, chosen_voice)
    await communicate.save(path)
    return path
