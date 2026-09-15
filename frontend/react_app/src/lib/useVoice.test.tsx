import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useVoice } from "./useVoice";
import { api } from "./api";

describe("useVoice", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("reports unsupported when MediaRecorder is absent", () => {
    // jsdom has no MediaRecorder by default.
    const { result } = renderHook(() => useVoice("tok"));
    expect(result.current.supported).toBe(false);
  });

  it("startRecording sets an error when unsupported", async () => {
    const { result } = renderHook(() => useVoice("tok"));
    await act(async () => {
      await result.current.startRecording();
    });
    expect(result.current.error).toBeTruthy();
    expect(result.current.recording).toBe(false);
  });

  it("stopAndTranscribe returns empty string with no active recorder", async () => {
    const { result } = renderHook(() => useVoice("tok"));
    let transcript = "unset";
    await act(async () => {
      transcript = await result.current.stopAndTranscribe();
    });
    expect(transcript).toBe("");
  });

  it("playReply calls the speak API and is a no-op for empty text", async () => {
    const speak = vi.spyOn(api, "speak").mockResolvedValue({
      audio_base64: "",
      audio_format: "mp3",
    });
    const { result } = renderHook(() => useVoice("tok"));

    await act(async () => {
      await result.current.playReply("");
    });
    expect(speak).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.playReply("hola", "Spanish");
    });
    await waitFor(() => expect(speak).toHaveBeenCalledWith("tok", "hola", "Spanish"));
  });
});
