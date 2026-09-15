"use client";

// Voice capture hook (Gate E): records microphone audio via MediaRecorder,
// base64-encodes it, and sends it to the backend /api/v1/voice/transcribe
// endpoint (local Whisper). Also exposes optional playback of a synthesized
// reply from /api/v1/voice/speak.
//
// Degrades gracefully: if the browser has no mic / MediaRecorder, or the
// backend voice extra isn't installed (503), `supported` is false or `error`
// is set and the caller keeps working in text-only mode.

import { useCallback, useRef, useState } from "react";
import { api } from "./api";

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      // Strip the "data:...;base64," prefix.
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

export interface UseVoice {
  supported: boolean;
  recording: boolean;
  busy: boolean;
  error: string | null;
  /** Start recording; resolves when recording has started. */
  startRecording: () => Promise<void>;
  /** Stop recording and return the transcript (empty string on failure). */
  stopAndTranscribe: (language?: string) => Promise<string>;
  /** Fetch + play synthesized speech for text; no-op on failure. */
  playReply: (text: string, language?: string) => Promise<void>;
}

const _supported =
  typeof window !== "undefined" &&
  typeof navigator !== "undefined" &&
  !!navigator.mediaDevices &&
  typeof (window as unknown as { MediaRecorder?: unknown }).MediaRecorder !== "undefined";

export function useVoice(token: string): UseVoice {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const startRecording = useCallback(async () => {
    setError(null);
    if (!_supported) {
      setError("Voice recording is not supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not access the microphone.");
    }
  }, []);

  const stopAndTranscribe = useCallback(
    async (language?: string): Promise<string> => {
      const recorder = recorderRef.current;
      if (!recorder) return "";
      setRecording(false);
      setBusy(true);

      const blob: Blob = await new Promise((resolve) => {
        recorder.onstop = () => resolve(new Blob(chunksRef.current, { type: "audio/webm" }));
        recorder.stop();
      });
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      recorderRef.current = null;

      try {
        const base64 = await blobToBase64(blob);
        const res = await api.transcribe(token, {
          audio_base64: base64,
          audio_format: "webm",
          language,
        });
        return res.transcript;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Transcription failed.");
        return "";
      } finally {
        setBusy(false);
      }
    },
    [token],
  );

  const playReply = useCallback(
    async (text: string, language?: string): Promise<void> => {
      if (!text.trim()) return;
      try {
        const res = await api.speak(token, text, language);
        if (!res.audio_base64) return;
        const audio = new Audio(`data:audio/${res.audio_format};base64,${res.audio_base64}`);
        await audio.play().catch(() => undefined);
      } catch {
        // TTS is best-effort; stay silent on failure (text reply already shown).
      }
    },
    [token],
  );

  return {
    supported: _supported,
    recording,
    busy,
    error,
    startRecording,
    stopAndTranscribe,
    playReply,
  };
}
