import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useProgress } from "./useProgress";
import { api } from "./api";

describe("useProgress", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads overview and growth for an authenticated user", async () => {
    vi.spyOn(api, "progressOverview").mockResolvedValue({
      total_sessions: 3,
      current_streak: 2,
      words_learned_total: 12,
      current_cefr: "A2",
      top_weaknesses: [{ error_type: "ser_vs_estar", occurrences: 4 }],
    });
    vi.spyOn(api, "vocabularyGrowth").mockResolvedValue([
      { date: "2026-01-01", new_words: 5, cumulative: 5 },
    ]);

    const { result } = renderHook(() => useProgress("token", "Spanish"));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.overview?.total_sessions).toBe(3);
    expect(result.current.growth).toHaveLength(1);
    expect(result.current.error).toBeNull();
  });

  it("does not fetch without a token", async () => {
    const spy = vi.spyOn(api, "progressOverview");
    renderHook(() => useProgress(null));
    expect(spy).not.toHaveBeenCalled();
  });

  it("surfaces errors", async () => {
    vi.spyOn(api, "progressOverview").mockRejectedValue(new Error("boom"));
    vi.spyOn(api, "vocabularyGrowth").mockResolvedValue([]);

    const { result } = renderHook(() => useProgress("token"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("boom");
  });
});
