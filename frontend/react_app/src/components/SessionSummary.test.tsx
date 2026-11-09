import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SessionSummary } from "./SessionSummary";
import type { SessionSummary as Summary } from "@/lib/api";

const summary: Summary = {
  correction_count: 1,
  corrections: [
    { original: "yo soy hambre", correction: "yo tengo hambre", explanation: "Hunger uses tener." },
  ],
  new_word_count: 2,
  new_words: ["mesa", "beber"],
  cultural_notes: [],
  level: { estimate: null, status: "insufficient evidence", working_level: "A1" },
  scenario: null,
  transfers: [],
};

describe("SessionSummary", () => {
  it("renders corrections, words and the level from the structured summary", () => {
    render(<SessionSummary summary={summary} report="text report" />);
    expect(screen.getByText("yo soy hambre")).toBeTruthy();
    expect(screen.getByText("yo tengo hambre")).toBeTruthy();
    expect(screen.getByText("Hunger uses tener.")).toBeTruthy();
    expect(screen.getByText("mesa")).toBeTruthy();
    // ADR-0031: no level is invented; the working level is labelled as the tutor's.
    expect(screen.getByText("not assessed yet")).toBeTruthy();
    expect(screen.getByText(/the tutor is speaking at A1/)).toBeTruthy();
    expect(screen.queryByText("text report")).toBeNull();
  });

  it("falls back to the text report from an older server", () => {
    render(<SessionSummary report="📊 Session Report" />);
    expect(screen.getByText("📊 Session Report")).toBeTruthy();
  });
});
