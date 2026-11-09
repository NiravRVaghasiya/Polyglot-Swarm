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
  const { overview, growth, loading, error } = useProgress(token, language);
  const reduceMotion = useReducedMotion();

  if (loading) {
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
  const { overview, growth, loading, error } = useProgress(token, language, refreshKey);

  if (loading && !overview) return <p className="text-slate-500">Loading progress…</p>;
  if (error) return <p className="text-red-600">{error}</p>;
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
        <Stat label="Streak" icon="flame" tone="text-orange-500" value={overview.current_streak} suffix="d" />
        <Stat label="Words" icon="book" tone="text-sky-500" value={overview.words_learned_total} />
        {/* The session heuristic's working level (how the tutor pitches its
            language), not an assessment — see the CEFR profile for that. */}
        <Stat label="Working level" icon="layers" tone="text-indigo-500" value={overview.current_cefr ?? "—"} />
        <Stat label="Sessions" icon="chat" tone="text-emerald-500" value={overview.total_sessions} />
      </m.div>

      <Card title="Vocabulary growth" icon="chart" delay={0.1}>
        {growth.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted">
            No vocabulary data yet — words you learn in sessions will show up here.
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

      <Card title="Top weaknesses" icon="target" delay={0.16}>
        {overview.top_weaknesses.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted">None yet — keep practicing!</p>
        ) : (
          <m.ul variants={stagger(0.05, 0.2)} initial="hidden" animate="show" className="space-y-3">
            {overview.top_weaknesses.map((w) => (
              <m.li key={w.error_type} variants={fadeUp} className="space-y-1">
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="font-medium">{w.error_type}</span>
                  <span className="tabular-nums text-muted">({w.occurrences}×)</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-surface2" aria-hidden="true">
                  <m.div
                    className="h-full origin-left rounded-full bg-gradient-to-r from-amber-400 to-rose-500"
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: w.occurrences / maxOccurrences }}
                    transition={{ ...easeOut, duration: 0.6, delay: 0.3 }}
                  />
                </div>
              </m.li>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Day streak" value={overview.current_streak} />
        <Stat label="Words" value={overview.words_learned_total} />
        {/* The session heuristic's working level (how the tutor pitches its
            language), not an assessment — see "Your level" for that. */}
        <Stat
          label="Tutor level"
          value={overview.current_cefr ?? "—"}
          title="The level the tutor speaks at. Your assessed level is under Today."
        />
        <Stat label="Sessions" value={overview.total_sessions} />
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 font-semibold">Vocabulary growth</h3>
        {growth.length === 0 ? (
          <p className="text-sm text-slate-500">
            New words from your conversations will show up here.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={growth}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Line type="monotone" dataKey="cumulative" name="Words" stroke="#4f46e5" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="rounded-lg border bg-white p-4">
        <h3 className="mb-2 font-semibold">Most common mistakes</h3>
        {overview.top_weaknesses.length === 0 ? (
          <p className="text-sm text-slate-500">None yet — keep practising!</p>
        ) : (
          <ul className="list-disc pl-5 text-sm">
            {overview.top_weaknesses.map((w) => (
              <li key={w.error_type}>
                {humanize(w.error_type)}{" "}
                <span className="text-slate-400">({w.occurrences}×)</span>
              </li>
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
  suffix = "",
  icon,
  tone,
}: {
  label: string;
  value: string | number;
  suffix?: string;
  icon: IconName;
  tone: string;
}) {
  return (
    <m.div
      variants={fadeUp}
      whileHover={{ y: -3 }}
      className="card flex flex-col items-center gap-1 p-3 text-center sm:p-4"
    >
      <Icon name={icon} size={18} className={tone} />
      <div className="text-2xl font-extrabold tabular-nums tracking-tight">
        {typeof value === "number" ? <CountUp value={value} /> : value}
        {suffix}
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</div>
    </m.div>
  );
}

/** Counts up to `value` on first render; renders the final value immediately
 *  when the user prefers reduced motion (and for screen readers always). */
function CountUp({ value }: { value: number }) {
  const reduceMotion = useReducedMotion();
  const [shown, setShown] = useState(reduceMotion ? value : 0);
  const from = useRef(0);

  useEffect(() => {
    if (reduceMotion) {
      setShown(value);
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
function Stat({
  label,
  value,
  title,
}: {
  label: string;
  value: string | number;
  title?: string;
}) {
  return (
    <div className="rounded-lg border bg-white p-3 text-center" title={title}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs uppercase text-slate-400">{label}</div>
    </div>
  );
}
