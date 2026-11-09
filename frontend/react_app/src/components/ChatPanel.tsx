"use client";

import { useEffect, useRef, useState } from "react";
import { api, type EndSessionResponse, Scenario } from "@/lib/api";
import { useVoice } from "@/lib/useVoice";
import { SessionSummary } from "./SessionSummary";

interface Message {
  role: "user" | "assistant";
  content: string;
}

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

export function ChatPanel({
  token,
  onSessionEnd,
}: {
  token: string;
  /** Called after a session is saved, so other views can refresh. */
  onSessionEnd?: () => void;
}) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [language, setLanguage] = useState("Spanish");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [ended, setEnded] = useState<EndSessionResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [speak, setSpeak] = useState(false);
  const voice = useVoice(token);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listScenarios(token).then(setScenarios).catch(() => setScenarios([]));
  }, [token]);

  // Keep the newest message in view.
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, busy]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.startSession(token, {
        language: scenarioId ? undefined : language,
        scenario_id: scenarioId || undefined,
      });
      setSessionId(res.session_id);
      setEnded(null);
      setMessages(res.opening_line ? [{ role: "assistant", content: res.opening_line }] : []);
    } catch (e) {
      setError(errorText(e, "Could not start a session."));
    } finally {
      setBusy(false);
    }
  }

  async function sendText(text: string) {
    if (!sessionId || !text.trim() || busy) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await api.chat(token, sessionId, text);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
      if (speak) void voice.playReply(res.reply, language);
    } catch (e) {
      setError(errorText(e, "The tutor could not answer. Try again."));
    } finally {
      setBusy(false);
    }
  }

  async function toggleMic() {
    if (voice.recording) {
      const transcript = await voice.stopAndTranscribe(language);
      if (transcript.trim()) await sendText(transcript);
    } else {
      await voice.startRecording();
    }
  }

  async function end() {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.endSession(token, sessionId);
      setEnded(res);
      setSessionId(null);
      setMessages([]);
      onSessionEnd?.();
    } catch (e) {
      setError(errorText(e, "Could not save the session."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {!sessionId ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className="rounded-md border p-2"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            placeholder="Language (e.g. Spanish)"
            aria-label="Target language"
            disabled={!!scenarioId}
            title={scenarioId ? "The scenario sets the language" : undefined}
          />
          <select
            className="min-w-0 flex-1 rounded-md border p-2"
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
            aria-label="Scenario"
          >
            <option value="">Free conversation</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} ({s.language.toUpperCase()}, {s.cefr_min}–{s.cefr_max})
              </option>
            ))}
          </select>
          <button
            className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            onClick={start}
            disabled={busy}
          >
            {ended ? "Start another session" : "Start session"}
          </button>
        </div>
      ) : (
        <>
          <div
            ref={logRef}
            className="h-80 space-y-2 overflow-y-auto rounded-lg border bg-white p-3"
            aria-live="polite"
          >
            {messages.length === 0 ? (
              <p className="text-sm text-slate-400">Say hello to start the conversation.</p>
            ) : null}
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex"}>
                <span
                  className={
                    "max-w-[85%] rounded-2xl px-3 py-2 text-sm " +
                    (m.role === "user"
                      ? "rounded-br-sm bg-indigo-600 text-white"
                      : "rounded-bl-sm bg-slate-100 text-slate-900")
                  }
                >
                  {m.content}
                </span>
              </div>
            ))}
            {busy ? (
              <div className="flex" aria-label="Tutor is typing">
                <span className="rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2 text-sm text-slate-400">
                  …
                </span>
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              className="min-w-0 flex-1 rounded-md border p-2"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendText(input)}
              placeholder="Type your message…"
              aria-label="Message"
            />
            <button
              className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              onClick={() => sendText(input)}
              disabled={busy || !input.trim()}
            >
              Send
            </button>
            {voice.supported && (
              <button
                className={
                  "rounded-md px-4 py-2 text-white disabled:opacity-50 " +
                  (voice.recording ? "bg-red-600" : "bg-emerald-600 hover:bg-emerald-700")
                }
                onClick={toggleMic}
                disabled={voice.busy}
                aria-label={voice.recording ? "Stop recording" : "Record voice"}
                title={voice.recording ? "Stop and send" : "Speak"}
              >
                {voice.recording ? "■ Stop" : voice.busy ? "…" : "🎤"}
              </button>
            )}
            <button
              className="rounded-md border px-4 py-2 hover:bg-slate-50 disabled:opacity-50"
              onClick={end}
              disabled={busy}
              title="End the session and see your summary"
            >
              End &amp; review
            </button>
          </div>
          {voice.supported && (
            <label className="flex items-center gap-2 text-sm text-slate-500">
              <input
                type="checkbox"
                checked={speak}
                onChange={(e) => setSpeak(e.target.checked)}
              />
              Speak replies aloud
            </label>
          )}
          {voice.error && <p className="text-sm text-red-600">{voice.error}</p>}
        </>
      )}

      {error ? (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      ) : null}

      {ended ? <SessionSummary summary={ended.summary} report={ended.report} /> : null}
    </div>
  );
}
