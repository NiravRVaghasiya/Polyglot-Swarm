"use client";

// Listening comprehension exercise (ADR-0034).
//
// Plays a task's synthesised audio, collects typed or chosen answers, and
// shows the per-kind result (recognition / comprehension / recall). Answers
// are never spoken, so the score does not depend on speech recognition or on
// the learner's speaking. An abstained dimension is shown as "not assessed",
// never as a score.

import { useEffect, useState } from "react";
import { AnimatePresence, m } from "motion/react";
import { api, type AssessmentReport, type ListeningTask } from "@/lib/api";
import { speedText } from "@/lib/labels";
import { Button } from "@/components/ui/Button";
import { ErrorNote, LoadingCard } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { easeOut, fadeUp, spring, stagger } from "@/components/ui/motion";

const KIND_LABEL: Record<string, string> = {
  listening_recognition: "Recognition",
  listening_comprehension: "Comprehension",
  listening_recall: "Recall",
};

const QUESTION_HINT: Record<string, string> = {
  recognition: "what you heard",
  comprehension: "what it meant",
  recall: "type the answer",
};

export function ListeningExercise({
  token,
  language = "Spanish",
  onSubmitted,
}: {
  token: string;
  language?: string;
  /** Called after answers are scored, so other views can refresh. */
  onSubmitted?: () => void;
}) {
  const [tasks, setTasks] = useState<ListeningTask[]>([]);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .listeningTasks(token, language)
      .then(setTasks)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load tasks."));
  }, [token, language]);

  const task = tasks[index];

  async function play() {
    if (!task) return;
    setPlaying(true);
    setError(null);
    try {
      const res = await api.listeningAudio(token, task.task_id);
      const audio = new Audio(`data:audio/${res.audio_format};base64,${res.audio_base64}`);
      audio.onended = () => setPlaying(false);
      await audio.play().catch(() => setPlaying(false));
    } catch {
      setPlaying(false);
      setError("Audio is unavailable right now.");
    }
  }

  async function submit() {
    if (!task) return;
    setError(null);
    setSubmitting(true);
    try {
      setReport(await api.submitListening(token, task.task_id, answers));
      onSubmitted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit answers.");
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !task) return <ErrorNote>{error}</ErrorNote>;
  if (!task) return <LoadingCard label="Loading listening tasks…" rows={3} />;

  const speed = speedText(task.rate);
  const answered = task.questions.filter((q) => (answers[q.question_id] ?? "").trim()).length;

  return (
    <section aria-label="Listening exercise" className="space-y-4">
      <AnimatePresence mode="wait" initial={false}>
        <m.div
          key={task.task_id}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0, transition: easeOut }}
          exit={{ opacity: 0, x: -24, transition: { duration: 0.15 } }}
          className="card space-y-5"
        >
          <header className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h3 className="font-semibold">
                Listening · {task.cefr} · {task.accent}
              </h3>
              <p className="text-xs text-muted">
                {[tasks.length > 1 ? `Clip ${index + 1} of ${tasks.length}` : null, speed]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <Button type="button" onClick={play} disabled={playing}>
              {playing ? <EqualizerBars /> : <Icon name="play" size={16} />}
              {playing ? "Playing…" : "Play audio"}
            </Button>
          </header>

          {tasks.length > 1 ? (
            <div className="h-1 overflow-hidden rounded-full bg-surface2" aria-hidden="true">
              <m.div
                className="h-full origin-left rounded-full bg-linear-to-r from-indigo-500 to-sky-500"
                initial={false}
                animate={{ scaleX: (index + (report ? 1 : 0)) / tasks.length }}
                transition={easeOut}
              />
            </div>
          ) : null}

          <m.div variants={stagger(0.06, 0.05)} initial="hidden" animate="show" className="space-y-5">
            {task.questions.map((q, n) => (
              <m.fieldset key={q.question_id} variants={fadeUp} className="space-y-2">
                <legend className="mb-2 flex items-start gap-2 font-medium">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-brand-soft text-xs font-bold text-link">
                    {n + 1}
                  </span>
                  <span>
                    {q.prompt}{" "}
                    <span className="ml-1 text-xs font-normal text-muted">({QUESTION_HINT[q.kind] ?? q.kind})</span>
                  </span>
                </legend>
                {q.options.length > 0 ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {q.options.map((opt) => {
                      const checked = answers[q.question_id] === opt;
                      return (
                        <label key={opt} className="block">
                          <input
                            type="radio"
                            className="peer sr-only"
                            name={q.question_id}
                            value={opt}
                            checked={checked}
                            onChange={() => setAnswers({ ...answers, [q.question_id]: opt })}
                          />
                          <m.span
                            whileTap={{ scale: 0.97 }}
                            transition={spring}
                            className={
                              "flex min-h-11 items-center gap-3 rounded-xl border px-3.5 py-2.5 text-sm transition-colors duration-200 " +
                              "peer-focus-visible:ring-2 peer-focus-visible:ring-brand/60 " +
                              (checked
                                ? "border-brand bg-brand-soft text-fg"
                                : "border-line bg-surface hover:border-brand/40 hover:bg-surface2")
                            }
                          >
                            <span
                              aria-hidden="true"
                              className={
                                "grid h-5 w-5 shrink-0 place-items-center rounded-full border-2 transition-colors duration-200 " +
                                (checked ? "border-brand bg-brand text-brand-fg" : "border-line")
                              }
                            >
                              {checked ? (
                                <m.span initial={{ scale: 0 }} animate={{ scale: 1 }} transition={spring}>
                                  <Icon name="check" size={12} strokeWidth={3} />
                                </m.span>
                              ) : null}
                            </span>
                            {opt}
                          </m.span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <input
                    className="field sm:max-w-sm"
                    aria-label={q.prompt}
                    placeholder="Your answer"
                    value={answers[q.question_id] ?? ""}
                    onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
                  />
                )}
              </m.fieldset>
            ))}
          </m.div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={submit}
              loading={submitting}
              disabled={answered === 0 || submitting}
            >
              Check answers
            </Button>
            {report && index + 1 < tasks.length && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setIndex(index + 1);
                  setAnswers({});
                  setReport(null);
                }}
              >
                Next clip
                <Icon name="arrowRight" size={16} />
              </Button>
            )}
          </div>

          <AnimatePresence>{error ? <ErrorNote key={error}>{error}</ErrorNote> : null}</AnimatePresence>

          <AnimatePresence>
            {report && (
              <m.ul
                key="results"
                aria-label="Results"
                variants={stagger(0.08)}
                initial="hidden"
                animate="show"
                exit={{ opacity: 0 }}
                className="space-y-2 rounded-xl border border-line/70 bg-surface2/50 p-3"
              >
                {report.dimensions.map((d) => {
                  const assessed = !(d.status === "abstained" || d.value === null);
                  const pct = assessed ? Math.round((d.value as number) * 100) : 0;
                  return (
                    <m.li key={d.dimension} variants={fadeUp} className="space-y-1.5">
                      <span className={"block text-sm font-medium " + (assessed ? "" : "text-muted")}>
                        {KIND_LABEL[d.dimension] ?? d.dimension}:{" "}
                        {assessed ? `${pct}%` : `not assessed (${d.reason})`}
                      </span>
                      {assessed ? (
                        <div className="h-2 overflow-hidden rounded-full bg-surface" aria-hidden="true">
                          <m.div
                            className={
                              "h-full origin-left rounded-full " +
                              (pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-rose-500")
                            }
                            initial={{ scaleX: 0 }}
                            animate={{ scaleX: pct / 100 }}
                            transition={{ ...easeOut, duration: 0.6, delay: 0.15 }}
                          />
                        </div>
                      ) : null}
                    </m.li>
                  );
                })}
              </m.ul>
            )}
          </AnimatePresence>
        </m.div>
      </AnimatePresence>
    </section>
  );
}

function EqualizerBars() {
  return (
    <span className="flex h-4 items-end gap-0.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-full w-1 origin-bottom animate-eq-bar rounded-full bg-current"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}
