"use client";

// Today's plan + CEFR skill map + insights — the "what should I practise
// today, and why?" view (Phase 16). Renders the learner model over the API.

import { usePlan } from "@/lib/usePlan";

const CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"];

export function TodaysPlan({
  token,
  language,
  goal,
}: {
  token: string;
  language?: string;
  goal?: string;
}) {
  const { plan, cefr, insights, loading, error } = usePlan(token, language, { goal });

  if (loading) return <p className="text-slate-500">Loading your plan…</p>;
  if (error) return <p className="text-red-600">{error}</p>;

  return (
    <div className="space-y-4">
      {/* Today's plan */}
      <div className="rounded border bg-white p-4">
        <h3 className="mb-2 font-semibold">Today&apos;s plan</h3>
        {!plan || plan.actions.length === 0 ? (
          <p className="text-slate-500">
            No plan yet — have a conversation session first.
          </p>
        ) : (
          <ol className="space-y-2">
            {plan.actions.map((a, i) => (
              <li key={`${a.type}-${a.target}-${i}`} className="rounded bg-slate-50 p-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium">
                    {a.type.replace(/_/g, " ")}
                    {a.skill ? (
                      <span className="ml-2 text-xs text-slate-400">({a.skill})</span>
                    ) : null}
                  </span>
                  <span className="text-xs text-slate-400">
                    {a.estimated_minutes} min · priority {a.priority.toFixed(2)}
                  </span>
                </div>
                <div className="text-sm text-slate-600">{a.reason}</div>
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* CEFR skill map */}
      <div className="rounded border bg-white p-4">
        <h3 className="mb-2 font-semibold">
          CEFR profile{cefr ? ` — overall ${cefr.overall}` : ""}
        </h3>
        {!cefr || Object.keys(cefr.skills).length === 0 ? (
          <p className="text-slate-500">No skill evidence yet.</p>
        ) : (
          <ul className="space-y-1">
            {Object.entries(cefr.skills).map(([skill, a]) => (
              <li key={skill} className="flex items-center gap-2">
                <span className="w-28 capitalize">{skill}</span>
                <span className="w-10 font-semibold">{a.cefr}</span>
                <div className="h-2 flex-1 rounded bg-slate-100">
                  <div
                    className="h-2 rounded bg-indigo-500"
                    style={{ width: `${Math.round(a.mastery * 100)}%` }}
                  />
                </div>
                <span className="w-24 text-right text-xs text-slate-400">
                  conf {a.confidence.toFixed(2)} · {a.sample_size} obs
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Insights */}
      {insights ? (
        <div className="rounded border bg-white p-4">
          <h3 className="mb-2 font-semibold">Insights</h3>
          <p className="text-sm">
            Overall level <span className="font-semibold">{insights.overall_cefr}</span>
            {insights.streak ? ` · ${insights.streak}-day streak` : ""}
          </p>
          {insights.weakest_skills.length > 0 ? (
            <p className="text-sm text-slate-600">
              Focus areas: {insights.weakest_skills.join(", ")}
            </p>
          ) : null}
          {insights.recommended_focus.length > 0 ? (
            <ul className="mt-1 list-disc pl-5 text-sm text-slate-600">
              {insights.recommended_focus.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Exported for tests / potential reuse.
export { CEFR_ORDER };
