import { describe, expect, it } from "vitest";
import type { PlanAction } from "./api";
import { describeAction, evidenceText, humanize, plural, speedText } from "./labels";

const action = (over: Partial<PlanAction>): PlanAction => ({
  type: "grammar_practice",
  target: "ser_vs_estar",
  skill: "grammar",
  reason: "r",
  priority: 0.5,
  estimated_minutes: 5,
  intent: "reinforcement",
  ...over,
});

describe("labels", () => {
  it("humanizes identifiers", () => {
    expect(humanize("preterite_vs_imperfect")).toBe("Preterite vs imperfect");
    expect(humanize("speaking")).toBe("Speaking");
    expect(humanize(null)).toBe("");
  });

  it("pluralizes", () => {
    expect(plural(1, "observation")).toBe("1 observation");
    expect(plural(0, "observation")).toBe("0 observations");
  });

  it("describes actions without internal identifiers", () => {
    const check = describeAction(action({ type: "diagnostic_check", target: "gender_agreement", intent: "assessment" }));
    expect(check.title).toBe("Quick check: Gender agreement");
    expect(check.description).not.toMatch(/_|observation\(s\)|priority/);

    expect(describeAction(action({ intent: "remediation" })).title).toBe("Practise: Ser vs estar");
    expect(describeAction(action({ intent: "progression" })).title).toBe("Level up: Ser vs estar");
    expect(describeAction(action({ type: "vocabulary_review", target: "mesa", intent: "review" })).title).toBe(
      "Review “mesa”",
    );
    expect(describeAction(action({ type: "something_unknown" })).title).toBe("Something unknown");
  });

  it("words evidence status and speed for learners", () => {
    expect(evidenceText("insufficient_evidence")).toBe("not enough practice yet");
    expect(evidenceText("validated")).toBe("confirmed");
    expect(speedText("-15%")).toBe("slower speech");
    expect(speedText("+0%")).toBeNull();
  });
});
