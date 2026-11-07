"use client";

// Today's plan + CEFR skill map + insights — the "what should I practise
// today, and why?" view (Phase 16). Renders the learner model over the API.
//
// ADR-0031: a CEFR band or mastery may be null ("not yet assessed"); it is
// never shown as a default level or as zero. Each skill shows its evidence
// status and, when known, the model's mastery range rather than one number.

import { ActionIntent, statusLabel } from "@/lib/api";
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

  const overall = cefr?.overall ?? null;

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
                    {a.intent ? (
                      <span
                        className="ml-2 rounded bg-indigo-50 px-1 text-xs text-indigo-700"
                        data-testid="action-intent"
                      >
                        {INTENT_LABEL[a.intent] ?? a.intent}
                      </span>
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
          CEFR profile
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
          <p className="text-slate-500">No skill evidence yet.</p>
        ) : (
          <ul className="space-y-1">
            {Object.entries(cefr.skills).map(([skill, a]) => (
              <li key={skill} className="flex items-center gap-2">
                <span className="w-28 capitalize">{skill}</span>
                <span className="w-10 font-semibold">{a.cefr ?? "—"}</span>
                <div
                  className="relative h-2 flex-1 rounded bg-slate-100"
                  title="mastery range (model estimate, not a calibrated probability)"
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
                <span className="w-40 text-right text-xs text-slate-400">
                  {statusLabel(a.status)} ·{" "}
                  {a.independent_count ?? a.sample_size} obs
                </span>
              </li>
            ))}
          </ul>
        )}
        {cefr?.unassessed_skills && cefr.unassessed_skills.length > 0 ? (
          <p className="mt-2 text-xs text-slate-500">
            Not yet assessed: {cefr.unassessed_skills.join(", ")}
          </p>
        ) : null}
      </div>

      {/* Insights */}
      {insights ? (
        <div className="rounded border bg-white p-4">
          <h3 className="mb-2 font-semibold">Insights</h3>
          <p className="text-sm">
            Overall level{" "}
            <span className="font-semibold">{insights.overall_cefr ?? "not yet assessed"}</span>
            {insights.streak ? ` · ${insights.streak}-day streak` : ""}
          </p>
          {insights.weakest_skills.length > 0 ? (
            <p className="text-sm text-slate-600">
              Focus areas: {insights.weakest_skills.join(", ")}
            </p>
          ) : null}
          {insights.needs_assessment && insights.needs_assessment.length > 0 ? (
            <p className="text-sm text-slate-500">
              Still finding your level in: {insights.needs_assessment.join(", ")}
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
