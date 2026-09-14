// Typed API client for the Polyglot Swarm backend.
//
// A thin wrapper over fetch that attaches the bearer token, JSON-encodes
// bodies, and surfaces API errors. All backend calls go through here so auth
// and error handling live in one place (and are unit-testable with a mocked
// fetch).

export const API_URL =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
}

export interface Scenario {
  id: string;
  title: string;
  language: string;
  cefr_min: string;
  cefr_max: string;
  location: string;
}

export interface HiddenFeedback {
  grammar: Record<string, unknown>[];
  vocabulary: Record<string, unknown>[];
  cultural: string[];
}

export interface ChatResponse {
  reply: string;
  hidden_feedback: HiddenFeedback;
}

export interface StartSessionResponse {
  session_id: string;
  language: string;
  cefr_level: string;
  opening_line: string;
}

export interface ProgressOverview {
  total_sessions: number;
  current_streak: number;
  words_learned_total: number;
  current_cefr: string | null;
  top_weaknesses: { error_type: string; occurrences: number }[];
}

export interface VocabPoint {
  date: string;
  new_words: number;
  cumulative: number;
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const { method = "GET", body, token } = options;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = (data && data.detail) || detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  // 204 No Content
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  register: (username: string, password: string) =>
    request<TokenResponse>("/api/v1/auth/register", {
      method: "POST",
      body: { username, password },
    }),

  login: (username: string, password: string) =>
    request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: { username, password },
    }),

  me: (token: string) =>
    request<{ user_id: string; username: string }>("/api/v1/auth/me", { token }),

  listScenarios: (token: string, language?: string) =>
    request<{ scenarios: Scenario[] }>(
      `/api/v1/scenarios${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { token },
    ).then((r) => r.scenarios),

  startSession: (
    token: string,
    opts: { language?: string; scenario_id?: string },
  ) =>
    request<StartSessionResponse>("/api/v1/sessions/start", {
      method: "POST",
      body: opts,
      token,
    }),

  chat: (token: string, session_id: string, message: string) =>
    request<ChatResponse>("/api/v1/chat", {
      method: "POST",
      body: { session_id, message },
      token,
    }),

  endSession: (token: string, session_id: string) =>
    request<{ report: string; persisted: Record<string, number> }>(
      `/api/v1/sessions/${session_id}/end`,
      { method: "POST", token },
    ),

  progressOverview: (token: string, language?: string) =>
    request<ProgressOverview>(
      `/api/v1/progress/overview${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { token },
    ),

  vocabularyGrowth: (token: string, language?: string) =>
    request<{ growth: VocabPoint[] }>(
      `/api/v1/progress/vocabulary${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { token },
    ).then((r) => r.growth),
};
