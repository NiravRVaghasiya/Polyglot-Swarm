"""Voice activity detection (VAD).

Detects whether an audio buffer actually contains speech, so the voice pipeline
can skip the (expensive) STT + agent + TTS stages on silence. The plan (Phase
15) puts VAD before STT in the pipeline.

Two backends:

- **webrtcvad** (optional, high quality) — used when the ``voice`` extra is
  installed and ``use_webrtc=True``.
- an **energy-based fallback** (dependency-free, deterministic) — used
  otherwise, so VAD works offline and in tests. It treats a near-silent buffer
  (very low mean absolute amplitude) as no-speech.

Following the rest of ``src/speech``, the heavy dependency is imported lazily
and a missing dependency raises :class:`SpeechDependencyError`.
"""

from __future__ import annotations

import audioop
import logging

from src.speech.stt import SpeechDependencyError

logger = logging.getLogger("polyglot.voice")

# Below this mean-absolute-amplitude (16-bit PCM), a buffer is treated as
# silence by the energy fallback. Conservative so genuine quiet speech passes.
_ENERGY_SILENCE_THRESHOLD = 200


def _energy_has_speech(audio: bytes, *, sample_width: int = 2) -> bool:
    """Dependency-free VAD: is the buffer's average amplitude above the floor?

    Uses ``audioop.rms`` (stdlib) on 16-bit PCM. Empty/near-silent buffers are
    no-speech; anything with meaningful energy is treated as speech.
    """
    if not audio:
        return False
    try:
        rms = audioop.rms(audio, sample_width)
    except audioop.error:
        # Not clean PCM of the expected width — fall back to a byte heuristic:
        # a buffer that is not almost-all-zero probably carries signal.
        nonzero = sum(1 for b in audio if b != 0)
        return nonzero > len(audio) * 0.05
    return rms >= _ENERGY_SILENCE_THRESHOLD


def _webrtc_has_speech(audio: bytes, *, sample_rate: int, aggressiveness: int) -> bool:
    """webrtcvad-based VAD. Raises SpeechDependencyError if webrtcvad missing."""
    try:
        import webrtcvad  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SpeechDependencyError(
            "webrtcvad is not installed. Install the voice extra: "
            "pip install 'polyglot-swarm[voice]'"
        ) from exc

    vad = webrtcvad.Vad(aggressiveness)
    # webrtcvad requires 10/20/30 ms frames of 16-bit mono PCM.
    frame_bytes = int(sample_rate * 0.03) * 2  # 30 ms, 16-bit
    if frame_bytes <= 0:
        return False
    for start in range(0, len(audio) - frame_bytes + 1, frame_bytes):
        frame = audio[start : start + frame_bytes]
        if vad.is_speech(frame, sample_rate):
            return True
    return False


def has_speech(
    audio: bytes,
    *,
    sample_rate: int = 16000,
    aggressiveness: int = 2,
    use_webrtc: bool = False,
) -> bool:
    """Return whether ``audio`` contains speech.

    Args:
        audio: raw 16-bit mono PCM bytes.
        sample_rate: sample rate in Hz (for the webrtc backend).
        aggressiveness: webrtcvad aggressiveness 0-3 (higher = more filtering).
        use_webrtc: use webrtcvad if available; otherwise the energy fallback.

    Falls back to the dependency-free energy detector when ``use_webrtc`` is
    False or webrtcvad is unavailable — so this always returns a usable answer
    offline.
    """
    if use_webrtc:
        try:
            return _webrtc_has_speech(audio, sample_rate=sample_rate, aggressiveness=aggressiveness)
        except SpeechDependencyError:
            logger.debug("webrtcvad unavailable; using energy-based VAD")
    return _energy_has_speech(audio)


def is_silence(audio: bytes, **kwargs: object) -> bool:
    """Convenience inverse of :func:`has_speech`."""
    return not has_speech(audio, **kwargs)  # type: ignore[arg-type]
