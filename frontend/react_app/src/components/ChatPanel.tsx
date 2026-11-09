"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, m } from "motion/react";
import { api, Scenario } from "@/lib/api";
import { useVoice } from "@/lib/useVoice";
import { Button } from "@/components/ui/Button";
import { Card, ErrorNote } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { easeOut, spring } from "@/components/ui/motion";

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
  const [starting, setStarting] = useState(false);
  const [ending, setEnding] = useState(false);
  const [speak, setSpeak] = useState(false);
  const voice = useVoice(token);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.listScenarios(token).then(setScenarios).catch(() => setScenarios([]));
  }, [token]);

  // Keep the newest message (or the typing indicator) in view.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo?.({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  async function start() {
    setStarting(true);
    try {
      const res = await api.startSession(token, {
        language: scenarioId ? undefined : language,
        scenario_id: scenarioId || undefined,
      });
      setSessionId(res.session_id);
      setReport(null);
      setMessages(res.opening_line ? [{ role: "assistant", content: res.opening_line }] : []);
    } finally {
      setStarting(false);
    }
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
    setEnding(true);
    try {
      const res = await api.endSession(token, sessionId);
      setReport(res.report);
      setSessionId(null);
    } finally {
      setEnding(false);
    }
  }

  return (
    <div className="space-y-4">
      <AnimatePresence mode="wait" initial={false}>
        {!sessionId ? (
          <m.div
            key="setup"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0, transition: easeOut }}
            exit={{ opacity: 0, y: -8, transition: { duration: 0.15 } }}
          >
            <Card title="Start a conversation" icon="chat">
              <p className="mb-4 text-sm text-muted">
                Chat freely in your target language, or pick a role-play scenario.
              </p>
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <div>
                  <label htmlFor="chat-language" className="field-label">
                    Language
                  </label>
                  <input
                    id="chat-language"
                    className="field"
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    placeholder="Language (e.g. Spanish)"
                    aria-label="Target language"
                  />
                </div>
                <div>
                  <label htmlFor="chat-scenario" className="field-label">
                    Scenario
                  </label>
                  <select
                    id="chat-scenario"
                    className="field"
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
                </div>
                <Button onClick={start} loading={starting} disabled={starting}>
                  Start session
                  {!starting ? <Icon name="arrowRight" size={16} /> : null}
                </Button>
              </div>
            </Card>
          </m.div>
        ) : (
          <m.div
            key="session"
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1, transition: easeOut }}
            exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.15 } }}
            className="card space-y-3 p-3 sm:p-4"
          >
            <div className="flex items-center justify-between gap-2 px-1">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inset-0 animate-pulse-ring rounded-full bg-emerald-500" />
                  <span className="relative h-2.5 w-2.5 rounded-full bg-emerald-500" />
                </span>
                Live session · {language}
              </span>
              <Button variant="secondary" size="sm" onClick={end} loading={ending} disabled={ending}>
                End
              </Button>
            </div>

            <div
              ref={scrollRef}
              className="h-[min(26rem,55dvh)] space-y-2 overflow-y-auto overscroll-contain rounded-xl bg-surface2/60 p-3"
              aria-live="polite"
              aria-label="Conversation"
            >
              {messages.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted">Say hello to get started.</p>
              ) : null}
              {messages.map((msg, i) => {
                const mine = msg.role === "user";
                return (
                  <m.div
                    key={i}
                    initial={{ opacity: 0, y: 10, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={spring}
                    style={{ originX: mine ? 1 : 0 }}
                    className={"flex " + (mine ? "justify-end" : "justify-start")}
                  >
                    <span
                      className={
                        "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-[15px] leading-relaxed shadow-sm " +
                        (mine
                          ? "rounded-br-md bg-brand text-brand-fg"
                          : "rounded-bl-md border border-line/70 bg-surface text-fg")
                      }
                    >
                      {msg.content}
                    </span>
                  </m.div>
                );
              })}
              <AnimatePresence>
                {busy ? (
                  <m.div
                    key="typing"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, transition: { duration: 0.12 } }}
                    className="flex"
                    role="status"
                  >
                    <span className="sr-only">Tutor is replying…</span>
                    <span
                      aria-hidden="true"
                      className="flex gap-1 rounded-2xl rounded-bl-md border border-line/70 bg-surface px-3.5 py-3"
                    >
                      {[0, 1, 2].map((d) => (
                        <span
                          key={d}
                          className="h-1.5 w-1.5 animate-typing-dot rounded-full bg-muted"
                          style={{ animationDelay: `${d * 0.15}s` }}
                        />
                      ))}
                    </span>
                  </m.div>
                ) : null}
              </AnimatePresence>
            </div>

            <div className="flex gap-2">
              <input
                className="field min-w-0 flex-1"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendText(input)}
                placeholder="Type your message…"
                aria-label="Message"
              />
              {voice.supported && (
                <span className="relative">
                  {voice.recording ? (
                    <span className="pointer-events-none absolute inset-0 animate-pulse-ring rounded-xl bg-red-500" />
                  ) : null}
                  <Button
                    size="icon"
                    variant={voice.recording ? "danger" : "success"}
                    onClick={toggleMic}
                    disabled={voice.busy}
                    aria-label={voice.recording ? "Stop recording" : "Record voice"}
                    title={voice.recording ? "Stop and send" : "Speak"}
                  >
                    {voice.busy ? (
                      <span aria-hidden="true">…</span>
                    ) : (
                      <Icon name={voice.recording ? "stop" : "mic"} size={18} />
                    )}
                  </Button>
                </span>
              )}
              <Button onClick={() => sendText(input)} disabled={busy}>
                <Icon name="send" size={16} />
                <span className="hidden sm:inline">Send</span>
                <span className="sr-only sm:hidden">Send</span>
              </Button>
            </div>

            {voice.supported && (
              <label className="flex w-fit items-center gap-2.5 px-1 text-sm text-muted">
                {/* Native checkbox (still the accessible control) styled as a switch. */}
                <span className="relative inline-flex h-6 w-10 shrink-0">
                  <input
                    type="checkbox"
                    className="peer sr-only"
                    checked={speak}
                    onChange={(e) => setSpeak(e.target.checked)}
                  />
                  <span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-full bg-line transition-colors duration-200 peer-checked:bg-brand peer-focus-visible:ring-2 peer-focus-visible:ring-brand/60 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-bg"
                  />
                  <span
                    aria-hidden="true"
                    className="absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow transition-transform duration-200 peer-checked:translate-x-4"
                  />
                </span>
                <Icon name="volume" size={16} />
                Speak replies aloud
              </label>
            )}
            <AnimatePresence>
              {voice.error ? <ErrorNote key={voice.error}>{voice.error}</ErrorNote> : null}
            </AnimatePresence>
          </m.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {report ? (
          <m.div
            key="report"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0, transition: { ...easeOut, delay: 0.1 } }}
            exit={{ opacity: 0 }}
          >
            <Card title="Session report" icon="sparkles">
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-fg">{report}</pre>
            </Card>
          </m.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
