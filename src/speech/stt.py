"""Speech-to-text via local Whisper.

Transcribes audio to text with an optional language hint. Whisper (and torch)
are heavy and optional — they are imported lazily inside functions and live
behind the ``voice`` extra, so importing this module never requires them. If
the dependency is missing at call time a clear :class:`SpeechDependencyError`
is raised rather than a bare ImportError.

Whisper language hints use ISO codes (``es``, ``pl``, ``it``); this module maps
the app's free-form language names to those codes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

# Free-form language name -> Whisper ISO code.
_LANG_NAME_TO_CODE = {
    "spanish": "es",
    "polish": "pl",
    "italian": "it",
    "english": "en",
}


class SpeechDependencyError(RuntimeError):
    """Raised when an optional speech dependency is not installed."""


def language_to_whisper_code(language: str | None) -> str | None:
    """Map a free-form language name (or code) to a Whisper ISO code."""
    if not language:
        return None
    key = language.strip().lower()
    if key in _LANG_NAME_TO_CODE:
        return _LANG_NAME_TO_CODE[key]
    # Already a 2-letter code?
    if len(key) == 2:
        return key
    return None


@lru_cache(maxsize=2)
def _load_model(model_size: str) -> Any:
    """Load (and cache) a Whisper model. Raises if whisper is unavailable."""
    try:
        import whisper  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SpeechDependencyError(
            "Whisper is not installed. Install the voice extra: "
            "pip install 'polyglot-swarm[voice]'"
        ) from exc
    return whisper.load_model(model_size)


def transcribe(
    audio_path: str,
    *,
    language: str | None = None,
    model_size: str = "base",
) -> str:
    """Transcribe an audio file to text.

    Args:
        audio_path: Path to an audio file Whisper can read.
        language: Free-form language name or ISO code to hint the model.
        model_size: Whisper model size ("tiny", "base", "small", ...).

    Returns:
        The transcribed text (stripped).
    """
    model = _load_model(model_size)
    code = language_to_whisper_code(language)
    result = model.transcribe(audio_path, language=code) if code else model.transcribe(audio_path)
    return str(result.get("text", "")).strip()
