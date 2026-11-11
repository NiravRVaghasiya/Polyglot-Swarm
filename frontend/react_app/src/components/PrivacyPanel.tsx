"use client";

// Self-service data export and deletion (the API's /privacy endpoints act
// only on the signed-in learner's own data).

import { useState } from "react";
import { AnimatePresence, m } from "motion/react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { ErrorNote } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { easeOut } from "@/components/ui/motion";

const CONFIRM_WORD = "DELETE";

export function PrivacyPanel({ token, onDeleted }: { token: string; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.exportData(token);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `polyglot-swarm-data-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not export your data.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteData(token);
      onDeleted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete your data.");
      setBusy(false);
    }
  }

  return (
    <div className="card space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="flex items-start gap-2 text-sm text-muted">
          <Icon name="book" size={16} className="mt-0.5 shrink-0" />
          Download everything stored about you: your account, lessons and learning record.
        </p>
        <Button type="button" variant="secondary" onClick={download} disabled={busy}>
          Download my data
        </Button>
      </div>

      <div className="border-t border-line pt-4">
        {!confirming ? (
            <div>
              <button
                type="button"
                className="rounded-sm text-sm font-semibold text-danger hover:underline"
                onClick={() => setConfirming(true)}
              >
                Delete my account and data…
              </button>
            </div>
          ) : (
            <m.div
              key="confirm"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0, transition: easeOut }}
              className="space-y-3 rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-fg"
            >
              <p className="flex items-start gap-2">
                <Icon name="alert" size={16} className="mt-0.5 shrink-0 text-danger" />
                <span>
                  This permanently deletes your account, lessons and progress. It cannot be undone.
                  Copies in backups expire within 30 days.
                </span>
              </p>
              <label className="block font-medium">
                Type <span className="font-mono font-bold text-danger">{CONFIRM_WORD}</span> to confirm
                <input
                  className="field mt-1.5 sm:w-56"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  aria-label={`Type ${CONFIRM_WORD} to confirm`}
                  autoComplete="off"
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="danger"
                  onClick={remove}
                  disabled={busy || typed !== CONFIRM_WORD}
                >
                  Delete permanently
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setConfirming(false);
                    setTyped("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </m.div>
          )}
      </div>
      <AnimatePresence>{error ? <ErrorNote key={error}>{error}</ErrorNote> : null}</AnimatePresence>
    </div>
  );
}
