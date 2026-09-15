# 0018. Voice activity detection & pronunciation integration (Phase 15)

- Status: Accepted
- Date: 2026-09-14

## Context

The voice pipeline (STT → agent → TTS) and pronunciation assessment already
existed, but there was no voice activity detection, so silence still triggered
the expensive STT/agent/TTS stages, and pronunciation scoring was limited to
scripted turns. The plan wants VAD in front of STT and pronunciation evaluated
separately from the transcript.

## Decision

- Add `src/speech/vad.py`: `has_speech(audio)` with an optional `webrtcvad`
  backend and a dependency-free energy-based fallback (using stdlib
  `audioop`), following the lazy-import + `SpeechDependencyError("voice extra")`
  pattern used across `src/speech`. The fallback makes VAD usable offline and in
  tests.
- Wire VAD into `VoicePipeline.handle_audio` as the first stage: on no-speech it
  returns the empty result without running STT/agent/TTS (recorded in
  `trace`). VAD is injectable (a synchronous `bytes -> bool`) and defaults to
  the energy detector.
- Allow pronunciation scoring on a normal turn via `handle_audio(...,
  expected_text=...)`; `handle_scripted_audio` now delegates to it. The
  `{transcript, reply, audio, pronunciation}` result shape and the silence-skip
  contract are preserved.

## Consequences

- Silence no longer wastes STT/LLM/TTS work; the pipeline short-circuits early.
- Pronunciation feedback is available whenever an expected utterance is known,
  not only in scripted mode.
- Voice remains fully optional and offline-capable; heavy deps (whisper,
  edge-tts, livekit, webrtcvad) are only required when actually used.
