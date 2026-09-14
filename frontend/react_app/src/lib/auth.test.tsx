import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, renderHook, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./auth";
import { api } from "./api";

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("auth context", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("starts unauthenticated", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.token).toBeNull();
  });

  it("login stores token and persists to localStorage", async () => {
    vi.spyOn(api, "login").mockResolvedValue({
      access_token: "tok-123",
      token_type: "bearer",
      user_id: "u-1",
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {
      await result.current.login("alice", "pw");
    });

    expect(result.current.token).toBe("tok-123");
    expect(result.current.userId).toBe("u-1");
    expect(localStorage.getItem("polyglot_token")).toBe("tok-123");
  });

  it("restores a saved session on mount", async () => {
    localStorage.setItem("polyglot_token", "saved-tok");
    localStorage.setItem("polyglot_user", "u-9");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.token).toBe("saved-tok");
    expect(result.current.userId).toBe("u-9");
  });

  it("logout clears token and storage", async () => {
    localStorage.setItem("polyglot_token", "t");
    localStorage.setItem("polyglot_user", "u");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.logout());

    expect(result.current.token).toBeNull();
    expect(localStorage.getItem("polyglot_token")).toBeNull();
  });

  it("useAuth outside provider throws", () => {
    function Bad() {
      useAuth();
      return null;
    }
    // Suppress the expected React error log.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Bad />)).toThrow(/within AuthProvider/);
    spy.mockRestore();
  });
});
