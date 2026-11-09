"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { humanize } from "@/lib/labels";
import { useProgress } from "@/lib/useProgress";

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

  if (loading && !overview) return <p className="text-slate-500">Loading progress…</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!overview) return null;

  return (
    <div className="space-y-4">
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
          </ul>
        )}
      </div>
    </div>
  );
}

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
