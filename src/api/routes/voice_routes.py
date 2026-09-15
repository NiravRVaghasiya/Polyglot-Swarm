"""Voice routes: speech-to-text and text-to-speech for the web frontend.

The React app records microphone audio, base64-encodes it, and POSTs it here
to be transcribed; it can also request synthesized speech for a reply. Audio
is carried as base64 in JSON (rather than multipart) so the endpoints need no
extra server dependency and are testable with the JSON ``TestClient`` like
every other route.

Both endpoints degrade gracefully: the speech stack (Whisper / Edge TTS) is an
optional extra, so if it isn't installed the endpoint returns HTTP 503 with a
clear message instead of a 500, and the frontend falls back to text-only.
"""

from __future__ import annotations

import base64
import binascii
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.deps import get_current_user
from src.api.schemas import (
    TranscribeRequest,
    TranscribeResponse,
    TtsRequest,
    TtsResponse,
)
from src.speech.stt import SpeechDependencyError

logger = logging.getLogger("polyglot.api.voice")

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe(
    req: TranscribeRequest, user_id: str = Depends(get_current_user)
) -> TranscribeResponse:
    """Transcribe base64-encoded audio to text (Whisper, local).

    Returns 400 for undecodable audio, 503 when the voice extra is not
    installed. Auth-scoped: only an authenticated user can transcribe.
    """
    from src.speech.stt import transcribe as stt_transcribe

    try:
        audio_bytes = base64.b64decode(req.audio_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 audio"
        ) from exc

    if not audio_bytes:
        return TranscribeResponse(transcript="")

    suffix = f".{req.audio_format}" if req.audio_format else ".wav"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        transcript = stt_transcribe(tmp_path, language=req.language)
        return TranscribeResponse(transcript=transcript)
    except SpeechDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@router.post("/speak", response_model=TtsResponse)
async def speak(req: TtsRequest, user_id: str = Depends(get_current_user)) -> TtsResponse:
    """Synthesize speech for ``text``, returning base64 MP3 audio (Edge TTS).

    Returns 503 when the voice extra is not installed. Empty text yields empty
    audio rather than an error.
    """
    from src.speech.tts import synthesize

    if not req.text.strip():
        return TtsResponse(audio_base64="", audio_format="mp3")

    try:
        audio = await synthesize(req.text, language=req.language)
    except SpeechDependencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 - a TTS outage is a 503, not a 500
        logger.warning("TTS synthesis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech synthesis is currently unavailable.",
        ) from exc

    return TtsResponse(audio_base64=base64.b64encode(audio).decode("ascii"), audio_format="mp3")
