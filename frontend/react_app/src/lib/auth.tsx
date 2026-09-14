"use client";

// Auth context: holds the bearer token + user, persists to localStorage, and
// exposes login/register/logout. A useAuthGuard hook redirects unauthenticated
// users to the login page.

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "./api";

const TOKEN_KEY = "polyglot_token";
const USER_KEY = "polyglot_user";

interface AuthState {
  token: string | null;
  userId: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore session from localStorage on mount.
    const t = typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
    const u = typeof window !== "undefined" ? localStorage.getItem(USER_KEY) : null;
    if (t) setToken(t);
    if (u) setUserId(u);
    setLoading(false);
  }, []);

  function persist(t: string, u: string) {
    setToken(t);
    setUserId(u);
    if (typeof window !== "undefined") {
      localStorage.setItem(TOKEN_KEY, t);
      localStorage.setItem(USER_KEY, u);
    }
  }

  async function login(username: string, password: string) {
    const res = await api.login(username, password);
    persist(res.access_token, res.user_id);
  }

  async function register(username: string, password: string) {
    const res = await api.register(username, password);
    persist(res.access_token, res.user_id);
  }

  function logout() {
    setToken(null);
    setUserId(null);
    if (typeof window !== "undefined") {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    }
  }

  return (
    <AuthContext.Provider value={{ token, userId, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
