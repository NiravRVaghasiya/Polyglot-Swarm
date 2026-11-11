"use client";

import { useEffect, useRef, useState } from "react";
import { animate, m, useReducedMotion } from "motion/react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { humanize } from "@/lib/labels";
import { useProgress } from "@/lib/useProgress";
import { Card, ErrorNote, LoadingCard, Skeleton } from "@/components/ui/Card";
import { Icon, type IconName } from "@/components/ui/Icon";
import { easeOut, fadeUp, stagger } from "@/components/ui/motion";

export function ProgressDashboard({
  token,
  language,
  refreshKey = 0,
}: {
  token: string;
  language?: string;
  /** Changing it reloads the numbers (e.g. after a session ends). */
  refreshKey?: number;
}) {
  const { overview, growth, loading, error } = useProgress(token, language, refreshKey);
  const reduceMotion = useReducedMotion();

  if (loading && !overview) {
    return (
      <div className="space-y-4" role="status" aria-live="polite">
        <span className="sr-only">Loading progress…</span>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
        <LoadingCard label="Loading vocabulary growth…" rows={2} />
      </div>
    );
  }
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!overview) return null;

  const maxOccurrences = Math.max(1, ...overview.top_weaknesses.map((w) => w.occurrences));

  return (
    <div className="space-y-4">
      <m.div
        variants={stagger(0.06)}
        initial="hidden"
        animate="show"
        className="grid grid-cols-2 gap-3 sm:grid-cols-4"
      >
        <Stat label="Day streak" icon="flame" tone="text-orange-500" value={overview.current_streak} />
        <Stat label="Words" icon="book" tone="text-sky-500" value={overview.words_learned_total} />
        {/* The session heuristic's working level (how the tutor pitches its
            language), not an assessment — see "Your level" for that. */}
        <Stat
          label="Tutor level"
          icon="layers"
          tone="text-indigo-500"
          value={overview.current_cefr ?? "—"}
          title="The level the tutor speaks at. Your assessed level is under Today."
        />
        <Stat label="Sessions" icon="chat" tone="text-emerald-500" value={overview.total_sessions} />
      </m.div>

      <Card title="Vocabulary growth" icon="chart" delay={0.1}>
        {growth.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            New words from your conversations will show up here.
          </p>
        ) : (
          <div className="text-muted" role="img" aria-label={growthSummary(growth)}>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={growth} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <defs>
                  <linearGradient id="growth-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.15} vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={24}
                />
                <YAxis
                  tick={{ fill: "currentColor", fontSize: 12 }}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ stroke: "#6366f1", strokeOpacity: 0.3 }}
                  contentStyle={{
                    background: "rgb(var(--surface))",
                    border: "1px solid rgb(var(--line))",
                    borderRadius: 12,
                    color: "rgb(var(--fg))",
                    boxShadow: "0 8px 24px -8px rgb(15 23 42 / 0.25)",
                  }}
                  labelStyle={{ color: "rgb(var(--muted))" }}
                />
                <Area
                  type="monotone"
                  dataKey="cumulative"
                  name="Words"
                  stroke="#6366f1"
                  strokeWidth={2.5}
                  fill="url(#growth-fill)"
                  activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
                  isAnimationActive={!reduceMotion}
                  animationDuration={900}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <Card title="Most common mistakes" icon="target" delay={0.16}>
        {overview.top_weaknesses.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted">None yet — keep practising!</p>
        ) : (
          <m.ul variants={stagger(0.05, 0.2)} initial="hidden" animate="show" className="space-y-3">
            {overview.top_weaknesses.map((w) => (
              <m.li key={w.error_type} variants={fadeUp} className="space-y-1">
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="font-medium">{humanize(w.error_type)}</span>
                  <span className="tabular-nums text-muted">({w.occurrences}×)</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface2" aria-hidden="true">
                  <m.div
                    className="h-full origin-left rounded-full bg-linear-to-r from-amber-400 to-rose-500"
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: w.occurrences / maxOccurrences }}
                    transition={{ ...easeOut, duration: 0.6, delay: 0.3 }}
                  />
                </div>
              </m.li>
            ))}
          </m.ul>
        )}
      </Card>
    </div>
  );
}

function growthSummary(growth: { date: string; cumulative: number }[]): string {
  const first = growth[0];
  const last = growth[growth.length - 1];
  return `Vocabulary growth chart: ${first.cumulative} words on ${first.date}, ${last.cumulative} words on ${last.date}.`;
}

function Stat({
  label,
  value,
  icon,
  tone,
  title,
}: {
  label: string;
  value: string | number;
  icon: IconName;
  tone: string;
  title?: string;
}) {
  return (
    <m.div
      variants={fadeUp}
      whileHover={{ y: -3 }}
      title={title}
      className="card flex flex-col items-center gap-1 p-3 text-center sm:p-4"
    >
      <Icon name={icon} size={18} className={tone} />
      <div className="text-2xl font-extrabold tabular-nums tracking-tight">
        {typeof value === "number" ? <CountUp value={value} /> : value}
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</div>
    </m.div>
  );
}

/** Counts up to `value` (and on later changes, from the previous value);
 *  renders the final value immediately when the user prefers reduced motion.
 *  Screen readers always get the final number. */
function CountUp({ value }: { value: number }) {
  const reduceMotion = useReducedMotion();
  const [shown, setShown] = useState(reduceMotion ? value : 0);
  const from = useRef(0);

  useEffect(() => {
    if (reduceMotion) {
      setShown(value);
      from.current = value;
      return;
    }
    const controls = animate(from.current, value, {
      duration: 0.9,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setShown(Math.round(v)),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, reduceMotion]);

  return (
    <>
      <span aria-hidden="true">{shown}</span>
      <span className="sr-only">{value}</span>
    </>
  );
}
