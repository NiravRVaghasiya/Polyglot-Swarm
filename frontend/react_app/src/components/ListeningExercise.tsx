"use client";

// Listening comprehension exercise (ADR-0034).
//
// Plays a task's synthesised audio, collects typed or chosen answers, and
// shows the per-kind result (recognition / comprehension / recall). Answers
// are never spoken, so the score does not depend on speech recognition or on
// the learner's speaking. An abstained dimension is shown as "not assessed",
// never as a score.

import { useEffect, useState } from "react";
import { api, type AssessmentReport, type ListeningTask } from "@/lib/api";
import { speedText } from "@/lib/labels";

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
    try {
      setReport(await api.submitListening(token, task.task_id, answers));
      onSubmitted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit answers.");
    }
  }

  if (error && !task) return <p role="alert" className="text-red-600">{error}</p>;
  if (!task) return <p className="text-slate-500">Loading listening tasks…</p>;

  const speed = speedText(task.rate);
  const answered = task.questions.filter((q) => (answers[q.question_id] ?? "").trim()).length;

  return (
    <section aria-label="Listening exercise" className="space-y-4 rounded-lg border bg-white p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-semibold">
            Listening · {task.cefr} · {task.accent}
          </h3>
          {speed ? <p className="text-xs text-slate-500">{speed}</p> : null}
        </div>
        <button
          type="button"
          onClick={play}
          disabled={playing}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {playing ? "Playing…" : "▶ Play audio"}
        </button>
      </header>

      {task.questions.map((q, n) => (
        <fieldset key={q.question_id} className="space-y-1">
          <legend className="mb-1 text-sm font-medium">
            {n + 1}. {q.prompt}{" "}
            <span className="font-normal text-slate-400">({QUESTION_HINT[q.kind] ?? q.kind})</span>
          </legend>
          {q.options.length > 0 ? (
            <div className="grid gap-1 sm:grid-cols-2">
              {q.options.map((opt) => (
                <label
                  key={opt}
                  className={
                    "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm " +
                    (answers[q.question_id] === opt
                      ? "border-indigo-400 bg-indigo-50"
                      : "hover:bg-slate-50")
                  }
                >
                  <input
                    type="radio"
                    name={q.question_id}
                    value={opt}
                    checked={answers[q.question_id] === opt}
                    onChange={() => setAnswers({ ...answers, [q.question_id]: opt })}
                  />
                  {opt}
                </label>
              ))}
            </div>
          ) : (
            <input
              aria-label={q.prompt}
              className="w-full rounded-md border p-2 text-sm sm:w-72"
              placeholder="Your answer"
              value={answers[q.question_id] ?? ""}
              onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
            />
          )}
        </fieldset>
      ))}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={answered === 0}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          Check answers
        </button>
        {report && index + 1 < tasks.length && (
          <button
            type="button"
            className="rounded-md border px-4 py-2 text-sm hover:bg-slate-50"
            onClick={() => {
              setIndex(index + 1);
              setAnswers({});
              setReport(null);
            }}
          >
            Next clip →
          </button>
        )}
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      {report && (
        <ul aria-label="Results" className="space-y-1 rounded-md bg-slate-50 p-3 text-sm">
          {report.dimensions.map((d) => (
            <li key={d.dimension}>
              {KIND_LABEL[d.dimension] ?? d.dimension}:{" "}
              {d.status === "abstained" || d.value === null
                ? `not assessed (${d.reason})`
                : `${Math.round(d.value * 100)}%`}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
