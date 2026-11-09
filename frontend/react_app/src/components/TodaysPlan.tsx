"use client";

// Today's plan + CEFR skill map + insights — the "what should I practise
// today, and why?" view (Phase 16). Renders the learner model over the API.
//
// ADR-0031: a CEFR band or mastery may be null ("not yet assessed"); it is
// never shown as a default level or as zero. Each skill shows its evidence
// status and, when known, the model's mastery range rather than one number.

import { m } from "motion/react";
import { ActionIntent, statusLabel } from "@/lib/api";
import { usePlan } from "@/lib/usePlan";
import { Card, ErrorNote, LoadingCard } from "@/components/ui/Card";
import { Icon, type IconName } from "@/components/ui/Icon";
import { easeOut, fadeUp, softSpring, stagger } from "@/components/ui/motion";

const CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"];

const INTENT_LABEL: Record<ActionIntent, string> = {
  assessment: "find your level",
  remediation: "fix a weakness",
  reinforcement: "consolidate",
  progression: "level up",
  introduction: "something new",
  review: "keep it fresh",
};

const INTENT_STYLE: Record<ActionIntent, { icon: IconName; tone: string }> = {
  assessment: { icon: "target", tone: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  remediation: { icon: "alert", tone: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
  reinforcement: { icon: "layers", tone: "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300" },
  progression: { icon: "arrowRight", tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  introduction: { icon: "sparkles", tone: "bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300" },
  review: { icon: "book", tone: "bg-slate-500/10 text-slate-700 dark:text-slate-300" },
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

  if (loading) {
    return (
      <div className="space-y-4">
        <LoadingCard label="Loading your plan…" rows={3} />
        <LoadingCard label="Loading your CEFR profile…" rows={2} />
      </div>
    );
  }
  if (error) return <ErrorNote>{error}</ErrorNote>;

  const overall = cefr?.overall ?? null;
  const totalMinutes = plan?.actions.reduce((sum, a) => sum + (a.estimated_minutes ?? 0), 0) ?? 0;

  return (
    <div className="space-y-4">
      {/* Today's plan */}
      <Card
        title="Today's plan"
        icon="sun"
        aside={
          totalMinutes > 0 ? (
            <span className="chip bg-surface2 text-muted">
              <Icon name="clock" size={12} /> ~{totalMinutes} min
            </span>
          ) : null
        }
      >
        {!plan || plan.actions.length === 0 ? (
          <EmptyState icon="chat">No plan yet — have a conversation session first.</EmptyState>
        ) : (
          <m.ol variants={stagger(0.05, 0.1)} initial="hidden" animate="show" className="space-y-2">
            {plan.actions.map((a, i) => {
              const style = a.intent ? INTENT_STYLE[a.intent] : undefined;
              return (
                <m.li
                  key={`${a.type}-${a.target}-${i}`}
                  variants={fadeUp}
                  whileHover={{ x: 2 }}
                  className="group flex gap-3 rounded-xl border border-line/60 bg-surface2/50 p-3 transition-colors duration-200 hover:border-brand/30 hover:bg-surface2"
                >
                  <span
                    className={
                      "grid h-9 w-9 shrink-0 place-items-center rounded-lg " +
                      (style?.tone ?? "bg-brand-soft text-link")
                    }
                    aria-hidden="true"
                  >
                    <Icon name={style?.icon ?? "book"} size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                      <span className="font-semibold">
                        {a.type.replace(/_/g, " ")}
                        {a.skill ? (
                          <span className="ml-2 text-xs font-normal text-muted">({a.skill})</span>
                        ) : null}
                        {a.intent ? (
                          <span
                            className={"chip ml-2 align-middle " + (style?.tone ?? "bg-brand-soft text-link")}
                            data-testid="action-intent"
                          >
                            {INTENT_LABEL[a.intent] ?? a.intent}
                          </span>
                        ) : null}
                      </span>
                      <span className="text-xs tabular-nums text-muted">
                        {a.estimated_minutes} min · priority {a.priority.toFixed(2)}
                      </span>
                    </div>
                    <div className="mt-0.5 text-sm text-muted">{a.reason}</div>
                  </div>
                </m.li>
              );
            })}
          </m.ol>
        )}
      </Card>

      {/* CEFR skill map */}
      <Card
        delay={0.06}
        icon="layers"
        title={
          <>
            CEFR profile
            {cefr ? (
              <span data-testid="overall-level">
                {" "}
                — overall {overall ?? "not yet assessed"}
                <span className="ml-1 text-xs font-normal text-muted">
                  ({statusLabel(cefr.overall_status)})
                </span>
              </span>
            ) : null}
          </>
        }
      >
        {!cefr || Object.keys(cefr.skills).length === 0 ? (
          <EmptyState icon="target">No skill evidence yet.</EmptyState>
        ) : (
          <m.ul variants={stagger(0.06, 0.15)} initial="hidden" animate="show" className="space-y-3">
            {Object.entries(cefr.skills).map(([skill, a]) => (
              <m.li
                key={skill}
                variants={fadeUp}
                className="grid grid-cols-[6.5rem_2.5rem_1fr] items-center gap-x-3 gap-y-1 sm:grid-cols-[7rem_2.5rem_1fr_auto]"
              >
                <span className="truncate font-medium capitalize">{skill}</span>
                <span
                  className={
                    "text-center text-sm font-bold " + (a.cefr ? "text-link" : "text-muted")
                  }
                >
                  {a.cefr ?? "—"}
                </span>
                <div
                  className="relative h-2.5 overflow-hidden rounded-full bg-surface2"
                  title="mastery range (model estimate, not a calibrated probability)"
                >
                  {a.mastery_low != null && a.mastery_high != null ? (
                    <m.div
                      className="absolute inset-y-0 origin-left rounded-full bg-gradient-to-r from-indigo-300 to-sky-300 dark:from-indigo-500/60 dark:to-sky-500/60"
                      style={{
                        left: `${Math.round(a.mastery_low * 100)}%`,
                        width: `${Math.round((a.mastery_high - a.mastery_low) * 100)}%`,
                      }}
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{ ...easeOut, duration: 0.6, delay: 0.25 }}
                    />
                  ) : null}
                  {a.mastery != null ? (
                    <m.div
                      className="absolute inset-y-0 w-1.5 rounded-full bg-brand shadow"
                      style={{ left: `${Math.round(a.mastery * 100)}%`, x: "-50%" }}
                      initial={{ opacity: 0, scaleY: 0 }}
                      animate={{ opacity: 1, scaleY: 1 }}
                      transition={{ ...softSpring, delay: 0.55 }}
                    />
                  ) : null}
                </div>
                <span className="col-span-3 text-xs text-muted sm:col-span-1 sm:w-36 sm:text-right">
                  {statusLabel(a.status)} · {a.independent_count ?? a.sample_size} obs
                </span>
              </m.li>
            ))}
          </m.ul>
        )}
        {cefr?.unassessed_skills && cefr.unassessed_skills.length > 0 ? (
          <p className="mt-3 text-xs text-muted">
            Not yet assessed: {cefr.unassessed_skills.join(", ")}
          </p>
        ) : null}
      </Card>

      {/* Insights */}
      {insights ? (
        <Card title="Insights" icon="sparkles" delay={0.12}>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span>
              Overall level{" "}
              <span className="font-semibold">{insights.overall_cefr ?? "not yet assessed"}</span>
            </span>
            {insights.streak ? (
              <span className="chip bg-orange-500/10 text-orange-700 dark:text-orange-300">
                <Icon name="flame" size={12} /> {insights.streak}-day streak
              </span>
            ) : null}
          </p>
          {insights.weakest_skills.length > 0 ? (
            <p className="mt-2 text-sm text-muted">
              Focus areas: {insights.weakest_skills.join(", ")}
            </p>
          ) : null}
          {insights.needs_assessment && insights.needs_assessment.length > 0 ? (
            <p className="mt-2 text-sm text-muted">
              Still finding your level in: {insights.needs_assessment.join(", ")}
            </p>
          ) : null}
          {insights.recommended_focus.length > 0 ? (
            <ul className="mt-3 space-y-1.5 text-sm">
              {insights.recommended_focus.map((r, i) => (
                <li key={i} className="flex gap-2">
                  <Icon name="check" size={16} className="mt-0.5 shrink-0 text-accent" />
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

function EmptyState({ icon, children }: { icon: IconName; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-line py-6 text-center text-sm text-muted">
      <span className="grid h-10 w-10 place-items-center rounded-full bg-surface2">
        <Icon name={icon} size={18} />
      </span>
      <p>{children}</p>
    </div>
  );
}

// Exported for tests / potential reuse.
export { CEFR_ORDER };
