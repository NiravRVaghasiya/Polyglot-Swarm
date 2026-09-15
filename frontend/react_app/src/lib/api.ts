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

// --- Learner model (Phase 16) ---
export interface PlanAction {
  type: string;
  target: string;
  skill: string | null;
  reason: string;
  priority: number;
  estimated_minutes: number;
}

export interface PlanResponse {
  language: string;
  goal: string;
  actions: PlanAction[];
}

export interface SkillAssessment {
  skill?: string | null;
  cefr: string;
  mastery: number;
  confidence: number;
  sample_size: number;
}

export interface CEFRProfile {
  language: string;
  overall: string;
  skills: Record<string, SkillAssessment>;
}

export interface SkillBelief {
  skill: string;
  mastery: number;
  uncertainty: number;
  sample_size: number;
}

export interface Insights {
  language: string;
  current_cefr: string | null;
  overall_cefr: string;
  weakest_skills: string[];
  top_weaknesses: { error_type: string; occurrences: number }[];
  recommended_focus: string[];
  streak: number;
}

export interface UserProfile {
  user_id: string;
  native_language: string;
  target_languages: string[];
  cefr_by_language: Record<string, string>;
  goals: string[];
  interests: string[];
  preferences: Record<string, unknown>;
}

export interface TranscribeResponse {
  transcript: string;
}

export interface TtsResponse {
  audio_base64: string;
  audio_format: string;
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

  // --- Learner model (Phase 16) ---
  todaysPlan: (
    token: string,
    opts: { language?: string; minutes?: number; goal?: string } = {},
  ) => {
    const params = new URLSearchParams();
    if (opts.language) params.set("language", opts.language);
    if (opts.minutes !== undefined) params.set("minutes", String(opts.minutes));
    if (opts.goal) params.set("goal", opts.goal);
    const qs = params.toString();
    return request<PlanResponse>(`/api/v1/learner/plan${qs ? `?${qs}` : ""}`, { token });
  },

  cefrProfile: (token: string, language?: string) =>
    request<CEFRProfile>(
      `/api/v1/learner/cefr${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { token },
    ),

  skillMap: (token: string, language?: string) =>
    request<{ language: string; skills: SkillBelief[] }>(
      `/api/v1/learner/skill-map${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { token },
    ).then((r) => r.skills),

  insights: (token: string, language?: string) =>
    request<Insights>(
      `/api/v1/learner/insights${language ? `?language=${encodeURIComponent(language)}` : ""}`,
      { token },
    ),

  // --- Profile / onboarding ---
  getProfile: (token: string) => request<UserProfile>("/api/v1/profile", { token }),

  updateProfile: (token: string, fields: Partial<UserProfile>) =>
    request<UserProfile>("/api/v1/profile", { method: "PUT", body: fields, token }),

  // --- Voice ---
  transcribe: (
    token: string,
    opts: { audio_base64: string; audio_format?: string; language?: string },
  ) =>
    request<TranscribeResponse>("/api/v1/voice/transcribe", {
      method: "POST",
      body: opts,
      token,
    }),

  speak: (token: string, text: string, language?: string) =>
    request<TtsResponse>("/api/v1/voice/speak", {
      method: "POST",
      body: { text, language },
      token,
    }),
};
