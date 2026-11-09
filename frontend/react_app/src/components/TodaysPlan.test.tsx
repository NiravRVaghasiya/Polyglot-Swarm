import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { TodaysPlan } from "./TodaysPlan";
import { api } from "@/lib/api";

// ADR-0031: a new learner has no CEFR level. The view must say so instead of
// showing a default band, and must label why each action is proposed.
describe("TodaysPlan with nullable CEFR", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows 'not yet assessed' and assessment intents for a new learner", async () => {
    vi.spyOn(api, "todaysPlan").mockResolvedValue({
      language: "Spanish",
      goal: "conversational",
      actions: [
        {
          type: "speaking_check",
          target: "speaking",
          skill: "speaking",
          reason: "no graded evidence for speaking yet",
          priority: 0.9,
          estimated_minutes: 3,
          intent: "assessment",
        },
      ],
    });
    vi.spyOn(api, "cefrProfile").mockResolvedValue({
      language: "Spanish",
      overall: null,
      overall_status: "insufficient_evidence",
      unassessed_skills: ["grammar", "speaking"],
      skills: {
        grammar: {
          cefr: null,
          status: "insufficient_evidence",
          mastery: 0.31,
          mastery_low: 0.05,
          mastery_high: 0.78,
          confidence: 0.05,
          sample_size: 1,
          independent_count: 1,
        },
      },
    });
    vi.spyOn(api, "insights").mockResolvedValue({
      language: "Spanish",
      current_cefr: null,
      overall_cefr: null,
      overall_status: "insufficient_evidence",
      weakest_skills: [],
      needs_assessment: ["grammar", "speaking"],
      top_weaknesses: [],
      recommended_focus: [],
      streak: 0,
    });

    render(<TodaysPlan token="t" language="Spanish" />);

    await waitFor(() => expect(screen.getByTestId("overall-level")).toBeTruthy());
    expect(screen.getByTestId("overall-level").textContent).toContain("not yet assessed");
    expect(screen.getByTestId("overall-level").textContent).toContain("not enough evidence");
    expect(screen.getByTestId("action-intent").textContent).toBe("find your level");
    expect(screen.getByText(/Not assessed yet: Grammar, Speaking/)).toBeTruthy();
    // No default band rendered anywhere.
    expect(screen.queryByText("A2")).toBeNull();
  });

  it("labels every adaptive-engine intent", async () => {
    const intents = [
      ["assessment", "find your level"],
      ["remediation", "fix a weakness"],
      ["reinforcement", "consolidate"],
      ["progression", "level up"],
      ["introduction", "something new"],
      ["review", "keep it fresh"],
    ] as const;
    vi.spyOn(api, "todaysPlan").mockResolvedValue({
      language: "Spanish",
      goal: "conversational",
      actions: intents.map(([intent], i) => ({
        type: "grammar_practice",
        target: `objective-${i}`,
        skill: "grammar",
        reason: "r",
        priority: 0.5,
        estimated_minutes: 5,
        intent,
      })),
    });
    vi.spyOn(api, "cefrProfile").mockResolvedValue({
      language: "Spanish",
      overall: null,
      overall_status: "insufficient_evidence",
      unassessed_skills: [],
      skills: {},
    });
    vi.spyOn(api, "insights").mockResolvedValue({
      language: "Spanish",
      current_cefr: null,
      overall_cefr: null,
      overall_status: "insufficient_evidence",
      weakest_skills: [],
      needs_assessment: [],
      top_weaknesses: [],
      recommended_focus: [],
      streak: 0,
    });

    render(<TodaysPlan token="t" language="Spanish" />);

    await waitFor(() => expect(screen.getAllByTestId("action-intent")).toHaveLength(6));
    expect(screen.getAllByTestId("action-intent").map((e) => e.textContent)).toEqual(
      intents.map(([, label]) => label),
    );
  });
});
