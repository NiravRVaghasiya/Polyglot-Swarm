"use client";

// Low-friction onboarding (Gate E): a first-run wizard that captures the one
// thing the learner model most needs to be useful — what language they're
// learning and what their goal is — then writes it to their profile. Shown
// once (when the profile has no goals yet); after that the dashboard renders
// normally.

import { useState } from "react";
import { api, UserProfile } from "@/lib/api";

const SUGGESTED_LANGUAGES = ["Spanish", "Polish", "Italian"];
const SUGGESTED_GOALS = [
  "Hold a conversation",
  "Travel",
  "Work / business",
  "Pass an exam",
  "Reconnect with heritage",
];

export function Onboarding({
  token,
  onComplete,
}: {
  token: string;
  onComplete: (profile: UserProfile) => void;
}) {
  const [language, setLanguage] = useState("Spanish");
  const [goal, setGoal] = useState(SUGGESTED_GOALS[0]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const profile = await api.updateProfile(token, {
        target_languages: [language],
        goals: [goal],
      });
      onComplete(profile);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save your preferences.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-5 rounded border bg-white p-6">
      <div>
        <h2 className="text-xl font-bold">Welcome 👋</h2>
        <p className="text-sm text-slate-600">
          Two quick questions so we can plan your practice.
        </p>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">What are you learning?</label>
        <input
          className="w-full rounded border p-2"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          list="onboarding-languages"
          aria-label="Target language"
        />
        <datalist id="onboarding-languages">
          {SUGGESTED_LANGUAGES.map((l) => (
            <option key={l} value={l} />
          ))}
        </datalist>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">What&apos;s your main goal?</label>
        <select
          className="w-full rounded border p-2"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          aria-label="Learning goal"
        >
          {SUGGESTED_GOALS.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        className="w-full rounded bg-indigo-600 px-4 py-2 text-white disabled:opacity-50"
        onClick={save}
        disabled={saving || !language.trim()}
      >
        {saving ? "Saving…" : "Start learning"}
      </button>
    </div>
  );
}
