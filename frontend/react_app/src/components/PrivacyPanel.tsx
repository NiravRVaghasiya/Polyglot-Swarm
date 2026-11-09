"use client";

// Self-service data export and deletion (the API's /privacy endpoints act
// only on the signed-in learner's own data).

import { useState } from "react";
import { api } from "@/lib/api";

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
    <div className="space-y-3 rounded-lg border bg-white p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-slate-600">
          Download everything stored about you: your account, lessons and learning record.
        </p>
        <button
          type="button"
          className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
          onClick={download}
          disabled={busy}
        >
          Download my data
        </button>
      </div>

      <div className="border-t pt-3">
        {!confirming ? (
          <button
            type="button"
            className="text-sm font-medium text-red-700 hover:underline"
            onClick={() => setConfirming(true)}
          >
            Delete my account and data…
          </button>
        ) : (
          <div className="space-y-2 rounded-md bg-red-50 p-3 text-sm text-red-900">
            <p>
              This permanently deletes your account, lessons and progress. It cannot be undone.
              Copies in backups expire within 30 days.
            </p>
            <label className="block">
              Type <span className="font-mono font-semibold">{CONFIRM_WORD}</span> to confirm
              <input
                className="mt-1 block w-full rounded-md border border-red-200 bg-white p-2 sm:w-48"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                aria-label={`Type ${CONFIRM_WORD} to confirm`}
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-md bg-red-700 px-4 py-2 font-medium text-white disabled:opacity-50"
                onClick={remove}
                disabled={busy || typed !== CONFIRM_WORD}
              >
                Delete permanently
              </button>
              <button
                type="button"
                className="rounded-md border border-red-200 bg-white px-4 py-2"
                onClick={() => {
                  setConfirming(false);
                  setTyped("");
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}
