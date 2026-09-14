"use client";

import { useEffect, useState } from "react";
import { api, Scenario } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export function ChatPanel({ token }: { token: string }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [report, setReport] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listScenarios(token).then(setScenarios).catch(() => setScenarios([]));
  }, [token]);

  async function start() {
    const res = await api.startSession(token, {
      language: scenarioId ? undefined : "Spanish",
      scenario_id: scenarioId || undefined,
    });
    setSessionId(res.session_id);
    setReport(null);
    setMessages(res.opening_line ? [{ role: "assistant", content: res.opening_line }] : []);
  }

  async function send() {
    if (!sessionId || !input.trim()) return;
    const text = input;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await api.chat(token, sessionId, text);
      setMessages((m) => [...m, { role: "assistant", content: res.reply }]);
    } finally {
      setBusy(false);
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
        <div className="flex gap-2">
          <select
            className="rounded border p-2"
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
          >
            <option value="">Free conversation</option>
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title} [{s.language}]
              </option>
            ))}
          </select>
          <button className="rounded bg-indigo-600 px-4 text-white" onClick={start}>
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
          <div className="flex gap-2">
            <input
              className="flex-1 rounded border p-2"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Type your message…"
            />
            <button
              className="rounded bg-indigo-600 px-4 text-white disabled:opacity-50"
              onClick={send}
              disabled={busy}
            >
              Send
            </button>
            <button className="rounded border px-4" onClick={end}>
              End
            </button>
          </div>
        </>
      )}

      {report && (
        <pre className="whitespace-pre-wrap rounded border bg-white p-3 text-sm">
          {report}
        </pre>
      )}
    </div>
  );
}
