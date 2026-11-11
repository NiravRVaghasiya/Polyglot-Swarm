"use client";

// The end-of-session report, rendered from the structured `summary` the API
// returns. Falls back to the plain-text report for older servers.

import { m } from "motion/react";
import type { SessionSummary as Summary } from "@/lib/api";
import { evidenceText, humanize } from "@/lib/labels";
import { Icon, type IconName } from "@/components/ui/Icon";
import { fadeUp, pop, stagger } from "@/components/ui/motion";

export function SessionSummary({ summary, report }: { summary?: Summary; report: string }) {
  if (!summary) {
    return (
      <pre className="card whitespace-pre-wrap font-sans text-sm leading-relaxed text-fg">{report}</pre>
    );
  }
  const { level, scenario } = summary;

  return (
    <m.div
      variants={stagger(0.07)}
      initial="hidden"
      animate="show"
      className="card space-y-5"
      aria-label="Session summary"
    >
      <m.div variants={fadeUp} className="flex items-center gap-3">
        <m.span
          variants={pop}
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-linear-to-br from-emerald-400 to-teal-500 text-white shadow-lift"
          aria-hidden="true"
        >
          <Icon name="check" size={22} strokeWidth={3} />
        </m.span>
        <h3 className="text-lg font-bold tracking-tight">Session complete</h3>
      </m.div>

      {scenario ? (
        <m.div
          variants={fadeUp}
          className={
            "rounded-xl border p-3 text-sm " +
            (scenario.passed
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
              : "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200")
          }
        >
          <p className="flex items-center gap-1.5 font-semibold">
            <Icon name={scenario.passed ? "target" : "alert"} size={16} />
            {humanize(scenario.id)}: {scenario.passed ? "goal reached" : "not quite yet"}
          </p>
          <p className="mt-0.5">
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
        </m.div>
      ) : null}

      <Section title="Corrections" icon="check">
        {summary.corrections.length === 0 ? (
          <p className="text-sm text-muted">No mistakes spotted this time.</p>
        ) : (
          <ul className="space-y-2">
            {summary.corrections.map((c, i) => (
              <li key={i} className="rounded-xl border border-line/60 bg-surface2/60 p-3 text-sm">
                <span className="text-danger line-through decoration-danger/60">{c.original}</span>
                <span className="mx-2 text-muted" aria-hidden="true">
                  →
                </span>
                <span className="font-semibold text-accent">{c.correction}</span>
                {c.explanation ? <p className="mt-1 text-muted">{c.explanation}</p> : null}
              </li>
            ))}
            {summary.correction_count > summary.corrections.length ? (
              <li className="text-xs text-muted">
                and {summary.correction_count - summary.corrections.length} more
              </li>
            ) : null}
          </ul>
        )}
      </Section>

      <Section title="New words" icon="book">
        {summary.new_words.length === 0 ? (
          <p className="text-sm text-muted">None this session.</p>
        ) : (
          <m.ul variants={stagger(0.035)} className="flex flex-wrap gap-2">
            {summary.new_words.map((w) => (
              <m.li
                key={w}
                variants={pop}
                className="rounded-full bg-brand-soft px-3 py-1 text-sm font-medium text-link"
              >
                {w}
              </m.li>
            ))}
            {summary.new_word_count > summary.new_words.length ? (
              <li className="px-1 py-1 text-xs text-muted">
                +{summary.new_word_count - summary.new_words.length} more
              </li>
            ) : null}
          </m.ul>
        )}
      </Section>

      {summary.cultural_notes.length > 0 ? (
        <Section title="Culture notes" icon="globe">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {summary.cultural_notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      {summary.transfers.length > 0 ? (
        <Section title="In your other languages" icon="layers">
          <ul className="space-y-1.5 text-sm">
            {summary.transfers.map((t) => (
              <li key={t.word}>
                <span className="font-semibold">{t.word}</span>
                {Object.entries(t.cognates).length > 0
                  ? ` — similar to ${Object.entries(t.cognates)
                      .map(([lang, w]) => `${w} (${lang})`)
                      .join(", ")}`
                  : ""}
                {t.false_friends.map((f) => (
                  <span
                    key={`${f.language}-${f.word}`}
                    className="mt-0.5 flex items-start gap-1 text-warn"
                  >
                    <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
                    <span>
                      False friend: {f.word} ({f.language}) {f.warning}
                    </span>
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <m.p variants={fadeUp} className="border-t border-line pt-3 text-sm text-muted">
        Level:{" "}
        <span className="font-semibold text-fg">
          {level.status === null ? "unavailable right now" : level.estimate ?? "not assessed yet"}
        </span>
        {level.status !== null ? ` (${evidenceText(level.status.replace(/ /g, "_"))})` : ""}
        <span> · the tutor is speaking at {level.working_level}</span>
      </m.p>
    </m.div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: IconName;
  children: React.ReactNode;
}) {
  return (
    <m.section variants={fadeUp}>
      <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold uppercase tracking-wider text-muted">
        <Icon name={icon} size={14} />
        {title}
      </h4>
      {children}
    </m.section>
  );
}
