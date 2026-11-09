"use client";

// The end-of-session report, rendered from the structured `summary` the API
// returns. Falls back to the plain-text report for older servers.

import type { SessionSummary as Summary } from "@/lib/api";
import { evidenceText, humanize } from "@/lib/labels";

export function SessionSummary({ summary, report }: { summary?: Summary; report: string }) {
  if (!summary) {
    return <pre className="whitespace-pre-wrap rounded-lg border bg-white p-4 text-sm">{report}</pre>;
  }
  const { level, scenario } = summary;

  return (
    <div className="space-y-4 rounded-lg border bg-white p-4" aria-label="Session summary">
      <h3 className="text-lg font-semibold">Session complete 🎉</h3>

      {scenario ? (
        <div
          className={
            "rounded-md p-3 text-sm " +
            (scenario.passed ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800")
          }
        >
          <p className="font-medium">
            {humanize(scenario.id)}: {scenario.passed ? "goal reached" : "not quite yet"}
          </p>
          <p>
            Target words used: {Math.round(scenario.vocab_coverage * 100)}% ·{" "}
            {scenario.grammar_ok ? "grammar on track" : "lots of grammar slips"}
          </p>
          {scenario.failure_reasons.length > 0 ? (
            <ul className="mt-1 list-disc pl-5">
              {scenario.failure_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      <section>
        <h4 className="mb-1 font-medium">Corrections</h4>
        {summary.corrections.length === 0 ? (
          <p className="text-sm text-slate-500">No mistakes spotted this time.</p>
        ) : (
          <ul className="space-y-2">
            {summary.corrections.map((c, i) => (
              <li key={i} className="rounded-md bg-slate-50 p-2 text-sm">
                <span className="text-red-700 line-through">{c.original}</span>
                <span className="mx-2 text-slate-400">→</span>
                <span className="font-medium text-emerald-700">{c.correction}</span>
                {c.explanation ? <p className="mt-1 text-slate-600">{c.explanation}</p> : null}
              </li>
            ))}
            {summary.correction_count > summary.corrections.length ? (
              <li className="text-xs text-slate-500">
                and {summary.correction_count - summary.corrections.length} more
              </li>
            ) : null}
          </ul>
        )}
      </section>

      <section>
        <h4 className="mb-1 font-medium">New words</h4>
        {summary.new_words.length === 0 ? (
          <p className="text-sm text-slate-500">None this session.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {summary.new_words.map((w) => (
              <li key={w} className="rounded-full bg-indigo-50 px-3 py-1 text-sm text-indigo-800">
                {w}
              </li>
            ))}
            {summary.new_word_count > summary.new_words.length ? (
              <li className="px-1 py-1 text-xs text-slate-500">
                +{summary.new_word_count - summary.new_words.length} more
              </li>
            ) : null}
          </ul>
        )}
      </section>

      {summary.cultural_notes.length > 0 ? (
        <section>
          <h4 className="mb-1 font-medium">Culture notes</h4>
          <ul className="list-disc pl-5 text-sm text-slate-700">
            {summary.cultural_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary.transfers.length > 0 ? (
        <section>
          <h4 className="mb-1 font-medium">In your other languages</h4>
          <ul className="space-y-1 text-sm text-slate-700">
            {summary.transfers.map((t) => (
              <li key={t.word}>
                <span className="font-medium">{t.word}</span>
                {Object.entries(t.cognates).length > 0
                  ? ` — similar to ${Object.entries(t.cognates)
                      .map(([lang, w]) => `${w} (${lang})`)
                      .join(", ")}`
                  : ""}
                {t.false_friends.map((f) => (
                  <span key={`${f.language}-${f.word}`} className="block text-amber-700">
                    ⚠ False friend: {f.word} ({f.language}) {f.warning}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <p className="border-t pt-3 text-sm text-slate-600">
        Level:{" "}
        <span className="font-medium text-slate-900">
          {level.status === null
            ? "unavailable right now"
            : level.estimate ?? "not assessed yet"}
        </span>
        {level.status !== null ? ` (${evidenceText(level.status.replace(/ /g, "_"))})` : ""}
        <span className="text-slate-400"> · the tutor is speaking at {level.working_level}</span>
      </p>
    </div>
  );
}
