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

const KIND_LABEL: Record<string, string> = {
  listening_recognition: "Recognition",
  listening_comprehension: "Comprehension",
  listening_recall: "Recall",
};

export function ListeningExercise({ token, language = "Spanish" }: { token: string; language?: string }) {
  const [tasks, setTasks] = useState<ListeningTask[]>([]);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listeningTasks(token, language)
      .then(setTasks)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load tasks."));
  }, [token, language]);

  const task = tasks[index];

  async function play() {
    if (!task) return;
    try {
      const res = await api.listeningAudio(token, task.task_id);
      const audio = new Audio(`data:audio/${res.audio_format};base64,${res.audio_base64}`);
      await audio.play().catch(() => undefined);
    } catch {
      setError("Audio is unavailable right now.");
    }
  }

  async function submit() {
    if (!task) return;
    setError(null);
    try {
      setReport(await api.submitListening(token, task.task_id, answers));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit answers.");
    }
  }

  if (error && !task) return <p role="alert">{error}</p>;
  if (!task) return <p>Loading listening tasks…</p>;

  return (
    <section aria-label="Listening exercise" className="space-y-3">
      <header>
        <h2 className="font-semibold">
          Listening · {task.cefr} · {task.accent} {task.rate !== "+0%" ? `· rate ${task.rate}` : ""}
        </h2>
        <button type="button" onClick={play}>
          ▶ Play
        </button>
      </header>
      {task.questions.map((q) => (
        <fieldset key={q.question_id}>
          <legend>
            {q.prompt} <small>({q.kind})</small>
          </legend>
          {q.options.length > 0 ? (
            q.options.map((opt) => (
              <label key={opt} className="block">
                <input
                  type="radio"
                  name={q.question_id}
                  value={opt}
                  checked={answers[q.question_id] === opt}
                  onChange={() => setAnswers({ ...answers, [q.question_id]: opt })}
                />{" "}
                {opt}
              </label>
            ))
          ) : (
            <input
              aria-label={q.prompt}
              value={answers[q.question_id] ?? ""}
              onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
            />
          )}
        </fieldset>
      ))}
      <button type="button" onClick={submit}>
        Check answers
      </button>
      {error && <p role="alert">{error}</p>}
      {report && (
        <ul aria-label="Results">
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
      {report && index + 1 < tasks.length && (
        <button
          type="button"
          onClick={() => {
            setIndex(index + 1);
            setAnswers({});
            setReport(null);
          }}
        >
          Next task
        </button>
      )}
    </section>
  );
}
