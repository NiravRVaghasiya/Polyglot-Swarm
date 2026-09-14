"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ChatPanel } from "@/components/ChatPanel";
import { ProgressDashboard } from "@/components/ProgressDashboard";

export default function HomePage() {
  const { token, loading, logout } = useAuth();
  const router = useRouter();

  // Auth guard: send unauthenticated users to /login once auth state is known.
  useEffect(() => {
    if (!loading && !token) router.replace("/login");
  }, [loading, token, router]);

  if (loading || !token) {
    return <main className="p-8 text-slate-500">Loading…</main>;
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">🌍 Polyglot Swarm</h1>
        <button className="text-sm text-slate-500" onClick={logout}>
          Log out
        </button>
      </header>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Practice</h2>
        <ChatPanel token={token} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Progress</h2>
        <ProgressDashboard token={token} />
      </section>
    </main>
  );
}
