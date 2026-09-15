import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { usePlan } from "./usePlan";
import { api } from "./api";

describe("usePlan", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads plan, cefr, and insights for an authenticated user", async () => {
    vi.spyOn(api, "todaysPlan").mockResolvedValue({
      language: "Spanish",
      goal: "conversational",
      actions: [
        {
          type: "review_vocab",
          target: "mesa",
          skill: "vocabulary",
          reason: "due for review",
          priority: 0.8,
          estimated_minutes: 1,
        },
      ],
    });
    vi.spyOn(api, "cefrProfile").mockResolvedValue({
      language: "Spanish",
      overall: "A2",
      skills: {
        vocabulary: { cefr: "B1", mastery: 0.6, confidence: 0.5, sample_size: 8 },
      },
    });
    vi.spyOn(api, "insights").mockResolvedValue({
      language: "Spanish",
      current_cefr: "A2",
      overall_cefr: "A2",
      weakest_skills: ["grammar"],
      top_weaknesses: [],
      recommended_focus: ["practice ser vs estar"],
      streak: 3,
    });

    const { result } = renderHook(() => usePlan("token", "Spanish"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.plan?.actions).toHaveLength(1);
    expect(result.current.cefr?.overall).toBe("A2");
    expect(result.current.insights?.weakest_skills).toContain("grammar");
    expect(result.current.error).toBeNull();
  });

  it("does not fetch without a token", () => {
    const spy = vi.spyOn(api, "todaysPlan");
    renderHook(() => usePlan(null));
    expect(spy).not.toHaveBeenCalled();
  });

  it("surfaces errors", async () => {
    vi.spyOn(api, "todaysPlan").mockRejectedValue(new Error("boom"));
    vi.spyOn(api, "cefrProfile").mockResolvedValue({
      language: "Spanish",
      overall: "A1",
      skills: {},
    });
    vi.spyOn(api, "insights").mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => usePlan("token"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("boom");
  });
});
