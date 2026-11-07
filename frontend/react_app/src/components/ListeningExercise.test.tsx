import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ListeningExercise } from "./ListeningExercise";
import { api } from "@/lib/api";

// ADR-0034: answers are typed or chosen (never spoken), results are shown per
// kind, and an abstained dimension is "not assessed" rather than a score.
describe("ListeningExercise", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("submits chosen and typed answers and shows per-kind results", async () => {
    vi.spyOn(api, "listeningTasks").mockResolvedValue([
      {
        task_id: "t1",
        language: "Spanish",
        cefr: "A1",
        voice: "es-MX-JorgeNeural",
        accent: "Mexico",
        rate: "+0%",
        style: "monologue",
        difficulty: 0.08,
        questions: [
          { question_id: "q1", kind: "recognition", prompt: "¿Ciudad?", options: ["Guadalajara", "Monterrey"] },
          { question_id: "q2", kind: "recall", prompt: "¿Edad?", options: [] },
        ],
      },
    ]);
    const submit = vi.spyOn(api, "submitListening").mockResolvedValue({
      submission_id: "s1",
      language: "Spanish",
      task_type: "listening",
      modality: "audio",
      status: "partial",
      dimensions: [
        { dimension: "listening_recognition", status: "ok", basis: "response", value: 1, confidence: 0.9, measures: {}, reason: "", feedback: [] },
        { dimension: "listening_recall", status: "abstained", basis: "response", value: null, confidence: 0, measures: {}, reason: "no answers given", feedback: [] },
      ],
      quality: {},
      issues: [],
      evidence_ids: ["e1"],
      observations: {},
    });

    render(<ListeningExercise token="tok" />);
    await waitFor(() => expect(screen.getByText(/Listening · A1/)).toBeTruthy());
    fireEvent.click(screen.getByLabelText("Guadalajara"));
    fireEvent.change(screen.getByLabelText("¿Edad?"), { target: { value: "diez" } });
    fireEvent.click(screen.getByText("Check answers"));

    await waitFor(() => expect(screen.getByText(/Recognition: 100%/)).toBeTruthy());
    expect(screen.getByText(/Recall: not assessed/)).toBeTruthy();
    expect(submit).toHaveBeenCalledWith("tok", "t1", { q1: "Guadalajara", q2: "diez" });
  });
});
