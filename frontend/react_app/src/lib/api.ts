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

// --- Multimodal assessment (ADR-0034) ---

export type AssessmentStatus = "ok" | "partial" | "abstained" | "failed";

export interface FeedbackItem {
  type: string;
  message: string;
  word?: string;
  heard?: string | null;
  start?: number | null;
  end?: number | null;
}

export interface DimensionResult {
  dimension: string;
  status: AssessmentStatus;
  /** What the judgment rests on: acoustic | transcript | timing | response | acoustic_proxy. */
  basis: string;
  value: number | null;
  confidence: number;
  measures: Record<string, unknown>;
  reason: string;
  feedback: FeedbackItem[];
}

export interface AssessmentReport {
  submission_id: string;
  language: string;
  task_type: string;
  modality: string;
  status: AssessmentStatus;
  dimensions: DimensionResult[];
  quality: Record<string, unknown>;
  issues: string[];
  evidence_ids: string[];
  observations: Record<string, unknown>;
}

export interface ListeningQuestion {
  question_id: string;
  kind: "recognition" | "comprehension" | "recall";
  prompt: string;
  options: string[];
}

export interface ListeningTask {
  task_id: string;
  language: string;
  cefr: string;
  voice: string;
  accent: string;
  rate: string;
  style: string;
  difficulty: number;
  questions: ListeningQuestion[];
}

export interface SpeakingRequest {
  audio_base64: string;
  audio_format?: string;
  language?: string;
  task_type?: "free_speech" | "read_aloud";
  target_text?: string;
  cefr?: string;
  retain_audio?: boolean;
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

// Feedback over the session's analyzed turns. A turn is analyzed after its
// reply, so a chat response carries feedback through the previous turn
// (`through_turn`); ADR-0036.
export interface HiddenFeedback {
  grammar: Record<string, unknown>[];
  vocabulary: Record<string, unknown>[];
  cultural: string[];
  through_turn: number;
}

export interface ChatResponse {
  reply: string;
  hidden_feedback: HiddenFeedback;
}

// The end-of-session report as data (`report` is the same, as text).
export interface SessionSummary {
  correction_count: number;
  corrections: { original: string; correction: string; explanation: string }[];
  new_word_count: number;
  new_words: string[];
  cultural_notes: string[];
  level: {
    /** Evidence-backed CEFR estimate; null until the evidence supports one. */
    estimate: string | null;
    /** Evidence status, or null if the learner model was unavailable. */
    status: string | null;
    /** The tutor's working level (how it pitches its language), not an assessment. */
    working_level: string;
  };
  scenario: {
    id: string;
    passed: boolean;
    objectives_completed: boolean;
    vocab_coverage: number;
    grammar_ok: boolean;
    failure_reasons: string[];
  } | null;
  transfers: {
    word: string;
    cognates: Record<string, string>;
    false_friends: { language: string; word: string; warning: string }[];
  }[];
}

export interface EndSessionResponse {
  report: string;
  /** Absent from servers older than this client. */
  summary?: SessionSummary;
  persisted: Record<string, number>;
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

// --- Learner model (Phase 16; nullable CEFR + evidence states, ADR-0031) ---
// A CEFR band or mastery is `null` until the evidence supports it — never a
// default level and never zero. `confidence` is an ordinal evidence index,
// not a calibrated probability.
export type EvidenceStatus =
  | "insufficient_evidence"
  | "provisional"
  | "estimated"
  | "validated";

// Intents of the adaptive next-best-activity engine (ADR-0033), the only
// planner behind /learner/plan.
export type ActionIntent =
  | "assessment"
  | "remediation"
  | "reinforcement"
  | "progression"
  | "introduction"
  | "review";

export interface PlanAction {
  // The activity, e.g. "grammar_practice", "vocabulary_review", "diagnostic_check".
  type: string;
  target: string;
  skill: string | null;
  reason: string;
  priority: number;
  estimated_minutes: number;
  intent: ActionIntent;
}

export interface PlanResponse {
  language: string;
  goal: string;
  actions: PlanAction[];
}

export interface SkillAssessment {
  skill?: string | null;
  cefr: string | null;
  status?: EvidenceStatus;
  mastery: number | null;
  mastery_low?: number | null;
  mastery_high?: number | null;
  uncertainty?: number;
  confidence: number;
  confidence_label?: "none" | "low" | "medium" | "high";
  sample_size: number;
  independent_count?: number;
  distinct_items?: number;
  coverage?: Record<string, unknown>;
  baseline_mastery?: number | null;
}

export interface CEFRProfile {
  language: string;
  overall: string | null;
  overall_status?: EvidenceStatus;
  overall_basis?: string[];
  unassessed_skills?: string[];
  method?: string;
  skills: Record<string, SkillAssessment>;
}

export interface SkillBelief {
  skill: string;
  mastery: number | null;
  uncertainty: number;
  sample_size: number;
  status?: EvidenceStatus;
  mastery_low?: number | null;
  mastery_high?: number | null;
  independent_count?: number;
  effective_n?: number;
  evidence_index?: number;
  evidence_quality?: number;
  coverage?: Record<string, unknown>;
  last_evidence_at?: string | null;
}

export interface Insights {
  language: string;
  /** The tutor's working level from session logs — not an assessment. */
  current_cefr: string | null;
  overall_cefr: string | null;
  overall_status?: EvidenceStatus;
  weakest_skills: string[];
  needs_assessment?: string[];
  top_weaknesses: { error_type: string; occurrences: number }[];
  recommended_focus: string[];
  streak: number;
}

/** Human-readable label for an evidence status. */
export function statusLabel(status: EvidenceStatus | undefined): string {
  switch (status) {
    case "provisional":
      return "provisional";
    case "estimated":
      return "estimated";
    case "validated":
      return "validated";
    default:
      return "not enough evidence";
  }
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
    request<EndSessionResponse>(`/api/v1/sessions/${session_id}/end`, {
      method: "POST",
      token,
    }),

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

  // --- Multimodal assessment (ADR-0034) ---
  assessSpeaking: (token: string, body: SpeakingRequest) =>
    request<AssessmentReport>("/api/v1/assessment/speaking", { method: "POST", body, token }),

  listeningTasks: (token: string, language = "Spanish") =>
    request<{ tasks: ListeningTask[] }>(
      `/api/v1/assessment/listening/tasks?language=${encodeURIComponent(language)}`,
      { token },
    ).then((r) => r.tasks),

  listeningAudio: (token: string, taskId: string) =>
    request<{ task_id: string; audio_base64: string; audio_format: string }>(
      `/api/v1/assessment/listening/tasks/${encodeURIComponent(taskId)}/audio`,
      { token },
    ),

  submitListening: (token: string, taskId: string, answers: Record<string, string | null>) =>
    request<AssessmentReport>(
      `/api/v1/assessment/listening/tasks/${encodeURIComponent(taskId)}/answers`,
      { method: "POST", body: { answers }, token },
    ),

  // --- Privacy: the caller's own data only ---
  exportData: (token: string) =>
    request<{ data: Record<string, unknown> }>("/api/v1/privacy/export", { token }),

  /** Permanently deletes the account and all its data; the token stops working. */
  deleteData: (token: string) =>
    request<{ deleted: Record<string, unknown> }>("/api/v1/privacy/data", {
      method: "DELETE",
      token,
    }),

  deleteSubmission: (token: string, submissionId: string) =>
    request<{ deleted: string }>(
      `/api/v1/assessment/submissions/${encodeURIComponent(submissionId)}`,
      { method: "DELETE", token },
    ),
};
