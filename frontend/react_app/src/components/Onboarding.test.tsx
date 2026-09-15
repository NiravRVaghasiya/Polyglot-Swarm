import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Onboarding } from "./Onboarding";
import { api, type UserProfile } from "@/lib/api";

describe("Onboarding wizard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the language and goal prompts", () => {
    render(<Onboarding token="t" onComplete={() => {}} />);
    expect(screen.getByLabelText("Target language")).toBeInTheDocument();
    expect(screen.getByLabelText("Learning goal")).toBeInTheDocument();
  });

  it("saves the chosen language + goal and calls onComplete", async () => {
    const profile = {
      user_id: "u1",
      native_language: "English",
      target_languages: ["Italian"],
      cefr_by_language: {},
      goals: ["Travel"],
      interests: [],
      preferences: {},
    };
    const update = vi.spyOn(api, "updateProfile").mockResolvedValue(profile);
    const onComplete = vi.fn();

    render(<Onboarding token="tok" onComplete={onComplete} />);

    fireEvent.change(screen.getByLabelText("Target language"), {
      target: { value: "Italian" },
    });
    fireEvent.change(screen.getByLabelText("Learning goal"), {
      target: { value: "Travel" },
    });
    fireEvent.click(screen.getByText("Start learning"));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(profile));
    expect(update).toHaveBeenCalledWith("tok", {
      target_languages: ["Italian"],
      goals: ["Travel"],
    });
  });

  it("shows an error when saving fails", async () => {
    vi.spyOn(api, "updateProfile").mockRejectedValue(new Error("network down"));
    render(<Onboarding token="t" onComplete={() => {}} />);
    fireEvent.click(screen.getByText("Start learning"));
    await waitFor(() => expect(screen.getByText("network down")).toBeInTheDocument());
  });

  it("disables the button while saving", async () => {
    let resolve: (value: UserProfile) => void = () => {};
    vi.spyOn(api, "updateProfile").mockReturnValue(
      new Promise<UserProfile>((r) => {
        resolve = r;
      }),
    );
    render(<Onboarding token="t" onComplete={() => {}} />);
    const btn = screen.getByText("Start learning");
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("Saving…")).toBeInTheDocument());
    resolve({
      user_id: "u1",
      native_language: "English",
      target_languages: ["Spanish"],
      cefr_by_language: {},
      goals: ["x"],
      interests: [],
      preferences: {},
    });
    await waitFor(() => expect(screen.getByText("Start learning")).toBeInTheDocument());
  });
});
