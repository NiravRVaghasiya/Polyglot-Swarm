"use client";

// Low-friction onboarding (Gate E): a first-run wizard that captures the one
// thing the learner model most needs to be useful — what language they're
// learning and what their goal is — then writes it to their profile. Shown
// once (when the profile has no goals yet); after that the dashboard renders
// normally.

import { useState } from "react";
import { AnimatePresence, m } from "motion/react";
import { api, UserProfile } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorNote } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { fadeUp, spring, stagger } from "@/components/ui/motion";

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
    <m.div
      variants={stagger(0.08)}
      initial="hidden"
      animate="show"
      className="card mx-auto max-w-md space-y-6 p-6 sm:p-7"
    >
      <m.div variants={fadeUp} className="space-y-2">
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-linear-to-br from-indigo-500 to-sky-500 text-white shadow-lift">
          <Icon name="sparkles" size={22} />
        </span>
        <h2 className="text-2xl font-extrabold tracking-tight">Welcome</h2>
        <p className="text-sm text-muted">Two quick questions so we can plan your practice.</p>
      </m.div>

      <m.div variants={fadeUp}>
        <label htmlFor="onboarding-language" className="field-label">
          <span className="mr-1.5 text-xs font-bold text-link">1</span>
          What are you learning?
        </label>
        <input
          id="onboarding-language"
          className="field"
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
        {/* Quick picks — same value as typing it in the field above. */}
        <div className="mt-2.5 flex flex-wrap gap-2" role="group" aria-label="Suggested languages">
          {SUGGESTED_LANGUAGES.map((l) => {
            const selected = language.trim().toLowerCase() === l.toLowerCase();
            return (
              <m.button
                key={l}
                type="button"
                whileTap={{ scale: 0.94 }}
                transition={spring}
                onClick={() => setLanguage(l)}
                aria-pressed={selected}
                className={
                  "relative min-h-9 rounded-full border px-3.5 text-sm font-medium transition-colors duration-200 " +
                  (selected
                    ? "border-transparent text-brand-fg"
                    : "border-line bg-surface text-muted hover:border-brand/40 hover:text-fg")
                }
              >
                {selected ? (
                  <m.span
                    layoutId="onboarding-language-pill"
                    transition={spring}
                    className="absolute inset-0 rounded-full bg-brand"
                  />
                ) : null}
                <span className="relative">{l}</span>
              </m.button>
            );
          })}
        </div>
      </m.div>

      <m.div variants={fadeUp}>
        <label htmlFor="onboarding-goal" className="field-label">
          <span className="mr-1.5 text-xs font-bold text-link">2</span>
          What&apos;s your main goal?
        </label>
        <select
          id="onboarding-goal"
          className="field"
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
      </m.div>

      <AnimatePresence>{error ? <ErrorNote key={error}>{error}</ErrorNote> : null}</AnimatePresence>

      <m.div variants={fadeUp}>
        <Button
          size="lg"
          className="w-full"
          onClick={save}
          disabled={saving || !language.trim()}
          loading={saving}
        >
          {saving ? "Saving…" : "Start learning"}
        </Button>
      </m.div>
    </m.div>
  );
}
