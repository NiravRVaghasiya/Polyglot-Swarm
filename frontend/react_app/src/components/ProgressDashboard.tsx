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
import { useProgress } from "@/lib/useProgress";

export function ProgressDashboard({
  token,
  language,
}: {
  token: string;
  language?: string;
}) {
  const { overview, growth, loading, error } = useProgress(token, language);

  if (loading) return <p className="text-slate-500">Loading progress…</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!overview) return null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Streak" value={`${overview.current_streak}d`} />
        <Stat label="Words" value={overview.words_learned_total} />
        <Stat label="CEFR" value={overview.current_cefr ?? "—"} />
        <Stat label="Sessions" value={overview.total_sessions} />
      </div>

      <div className="rounded border bg-white p-4">
        <h3 className="mb-2 font-semibold">Vocabulary growth</h3>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={growth}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="cumulative" stroke="#4f46e5" />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded border bg-white p-4">
        <h3 className="mb-2 font-semibold">Top weaknesses</h3>
        {overview.top_weaknesses.length === 0 ? (
          <p className="text-slate-500">None yet — keep practicing!</p>
        ) : (
          <ul className="list-disc pl-5">
            {overview.top_weaknesses.map((w) => (
              <li key={w.error_type}>
                {w.error_type}{" "}
                <span className="text-slate-400">({w.occurrences}×)</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border bg-white p-3 text-center">
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs uppercase text-slate-400">{label}</div>
    </div>
  );
}
