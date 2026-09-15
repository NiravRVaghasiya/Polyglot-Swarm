"use client";

import { useEffect, useState } from "react";
import { api, Scenario } from "@/lib/api";
import { useVoice } from "@/lib/useVoice";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export function ChatPanel({ token }: { token: string }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [language, setLanguage] = useState("Spanish");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [report, setReport] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [speak, setSpeak] = useState(false);
  const voice = useVoice(token);

  useEffect(() => {
    api.listScenarios(token).then(setScenarios).catch(() => setScenarios([]));
  }, [token]);

  async function start() {
    const res = await api.startSession(token, {
      language: scenarioId ? undefined : language,
      scenario_id: scenarioId || undefined,
    });
    setSessionId(res.session_id);
    setReport(null);
    setMessages(res.opening_line ? [{ role: "assistant", content: res.opening_line }] : []);
  }

  async function sendText(text: string) {
    if (!sessionId || !text.trim()) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await api.chat(token, sessionId, text);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
      if (speak) void voice.playReply(res.reply, language);
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
    const res = await api.endSession(token, sessionId);
    setReport(res.report);
    setSessionId(null);
  }

  return (
    <div className="space-y-3">
      {!sessionId ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className="rounded border p-2"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            placeholder="Language (e.g. Spanish)"
            aria-label="Target language"
          />
          <select
            className="rounded border p-2"
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
            aria-label="Scenario"
          >
            <option value="">Free conversation</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} [{s.language}]
              </option>
            ))}
          </select>
          <button className="rounded bg-indigo-600 px-4 py-2 text-white" onClick={start}>
            Start session
          </button>
        </div>
      ) : (
        <>
          <div className="h-80 overflow-y-auto rounded border bg-white p-3">
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : ""}>
                <span
                  className={
                    "my-1 inline-block rounded px-3 py-1 " +
                    (m.role === "user" ? "bg-indigo-100" : "bg-slate-100")
                  }
                >
                  {m.content}
                </span>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              className="min-w-0 flex-1 rounded border p-2"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendText(input)}
              placeholder="Type your message…"
              aria-label="Message"
            />
            <button
              className="rounded bg-indigo-600 px-4 py-2 text-white disabled:opacity-50"
              onClick={() => sendText(input)}
              disabled={busy}
            >
              Send
            </button>
            {voice.supported && (
              <button
                className={
                  "rounded px-4 py-2 text-white disabled:opacity-50 " +
                  (voice.recording ? "bg-red-600" : "bg-emerald-600")
                }
                onClick={toggleMic}
                disabled={voice.busy}
                aria-label={voice.recording ? "Stop recording" : "Record voice"}
                title={voice.recording ? "Stop and send" : "Speak"}
              >
                {voice.recording ? "■ Stop" : voice.busy ? "…" : "🎤"}
              </button>
            )}
            <button className="rounded border px-4 py-2" onClick={end}>
              End
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

      {report && (
        <pre className="whitespace-pre-wrap rounded border bg-white p-3 text-sm">{report}</pre>
      )}
    </div>
  );
}
