"use client";

// Today's plan + CEFR skill map + insights — the "what should I practise
// today, and why?" view (Phase 16). Renders the learner model over the API.
//
// ADR-0031: a CEFR band or mastery may be null ("not yet assessed"); it is
// never shown as a default level or as zero. Each skill shows its evidence
// status and, when known, the model's mastery range rather than one number.
//
// Titles and descriptions are learner-facing (lib/labels); the planner's own
// reason stays available behind "Why?".

import { ActionIntent, statusLabel } from "@/lib/api";
import { describeAction, evidenceText, humanize, plural } from "@/lib/labels";
import { usePlan } from "@/lib/usePlan";

const CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"];

const INTENT_LABEL: Record<ActionIntent, string> = {
  assessment: "find your level",
  remediation: "fix a weakness",
  reinforcement: "consolidate",
  progression: "level up",
  introduction: "something new",
  review: "keep it fresh",
};

const list = (items: string[]) => items.map(humanize).join(", ");

export function TodaysPlan({
  token,
  language,
  goal,
  refreshKey = 0,
}: {
  token: string;
  language?: string;
  goal?: string;
  /** Changing it reloads the plan (e.g. after a session ends). */
  refreshKey?: number;
}) {
  const { plan, cefr, insights, loading, error } = usePlan(token, language, { goal, refreshKey });

  if (loading && !plan) return <p className="text-slate-500">Loading your plan…</p>;
  if (error) return <p className="text-red-600">{error}</p>;

  const overall = cefr?.overall ?? null;

  return (
    <div className="space-y-4">
      {/* Today's plan */}
      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-3 font-semibold">Today&apos;s plan</h3>
        {!plan || plan.actions.length === 0 ? (
          <p className="text-slate-500">
            No plan yet — have a conversation session first.
          </p>
        ) : (
          <ol className="space-y-2">
            {plan.actions.map((a, i) => {
              const text = describeAction(a);
              return (
                <li key={`${a.type}-${a.target}-${i}`} className="rounded-md bg-slate-50 p-3">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-medium">{text.title}</span>
                    {a.intent ? (
                      <span
                        className="rounded bg-indigo-50 px-1.5 py-0.5 text-xs text-indigo-700"
                        data-testid="action-intent"
                      >
                        {INTENT_LABEL[a.intent] ?? a.intent}
                      </span>
                    ) : null}
                    <span className="ml-auto whitespace-nowrap text-xs text-slate-500">
                      ~{Math.max(1, Math.round(a.estimated_minutes))} min
                    </span>
                  </div>
                  {text.description ? (
                    <p className="mt-1 text-sm text-slate-600">{text.description}</p>
                  ) : null}
                  <details className="mt-1 text-xs text-slate-400">
                    <summary className="cursor-pointer select-none hover:text-slate-600">Why?</summary>
                    <p className="mt-1">{a.reason}</p>
                  </details>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {/* CEFR skill map */}
      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 font-semibold">
          Your level
          {cefr ? (
            <span data-testid="overall-level">
              {" "}
              — overall {overall ?? "not yet assessed"}
              <span className="ml-1 text-xs font-normal text-slate-400">
                ({statusLabel(cefr.overall_status)})
              </span>
            </span>
          ) : null}
        </h3>
        {!cefr || Object.keys(cefr.skills).length === 0 ? (
          <p className="text-sm text-slate-500">
            Practise a little and your level per skill (A1–C2) appears here.
          </p>
        ) : (
          <ul className="space-y-2">
            {Object.entries(cefr.skills).map(([skill, a]) => (
              <li key={skill} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="w-24 capitalize">{skill}</span>
                <span className="w-8 font-semibold">{a.cefr ?? "—"}</span>
                <div
                  className="relative h-2 min-w-[6rem] flex-1 rounded bg-slate-100"
                  title="Likely range of your mastery (a model estimate)"
                >
                  {a.mastery_low != null && a.mastery_high != null ? (
                    <div
                      className="absolute h-2 rounded bg-indigo-200"
                      style={{
                        left: `${Math.round(a.mastery_low * 100)}%`,
                        width: `${Math.round((a.mastery_high - a.mastery_low) * 100)}%`,
                      }}
                    />
                  ) : null}
                  {a.mastery != null ? (
                    <div
                      className="absolute h-2 w-1 rounded bg-indigo-600"
                      style={{ left: `${Math.round(a.mastery * 100)}%` }}
                    />
                  ) : null}
                </div>
                <span className="w-full text-xs text-slate-400 sm:w-auto sm:text-right">
                  {evidenceText(a.status)} · {plural(a.independent_count ?? a.sample_size, "answer")}
                </span>
              </li>
            ))}
          </ul>
        )}
        {cefr?.unassessed_skills && cefr.unassessed_skills.length > 0 ? (
          <p className="mt-2 text-xs text-slate-500">
            Not assessed yet: {list(cefr.unassessed_skills)}
          </p>
        ) : null}
      </div>

      {/* Insights. The plan above already shows the recommended activities,
          and "Your level" the skills not assessed yet. */}
      {insights && (insights.streak > 0 || insights.weakest_skills.length > 0) ? (
        <div className="rounded-lg border bg-white p-4">
          <h3 className="mb-2 font-semibold">Insights</h3>
          {insights.streak ? (
            <p className="text-sm">🔥 {plural(insights.streak, "day")} in a row</p>
          ) : null}
          {insights.weakest_skills.length > 0 ? (
            <p className="text-sm text-slate-600">Focus areas: {list(insights.weakest_skills)}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Exported for tests / potential reuse.
export { CEFR_ORDER };
