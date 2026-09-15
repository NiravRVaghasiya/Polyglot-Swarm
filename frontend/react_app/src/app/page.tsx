"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api, UserProfile } from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { ProgressDashboard } from "@/components/ProgressDashboard";
import { TodaysPlan } from "@/components/TodaysPlan";
import { Onboarding } from "@/components/Onboarding";

export default function HomePage() {
  const { token, loading, logout } = useAuth();
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);

  // Auth guard: send unauthenticated users to /login once auth state is known.
  useEffect(() => {
    if (!loading && !token) router.replace("/login");
  }, [loading, token, router]);

  // Load the profile so we know whether to show onboarding first.
  useEffect(() => {
    if (!token) return;
    let active = true;
    setProfileLoading(true);
    api
      .getProfile(token)
      .then((p) => {
        if (active) setProfile(p);
      })
      .catch(() => {
        if (active) setProfile(null);
      })
      .finally(() => {
        if (active) setProfileLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  const onOnboarded = useCallback((p: UserProfile) => setProfile(p), []);

  if (loading || !token || profileLoading) {
    return <main className="p-8 text-slate-500">Loading…</main>;
  }

  const needsOnboarding = !profile || profile.goals.length === 0;
  const language = profile?.target_languages?.[0];

  if (needsOnboarding) {
    return (
      <main className="mx-auto max-w-3xl space-y-6 p-6">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">🌍 Polyglot Swarm</h1>
          <button className="text-sm text-slate-500" onClick={logout}>
            Log out
          </button>
        </header>
        <Onboarding token={token} onComplete={onOnboarded} />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold sm:text-2xl">🌍 Polyglot Swarm</h1>
        <button className="text-sm text-slate-500" onClick={logout}>
          Log out
        </button>
      </header>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Today</h2>
        <TodaysPlan token={token} language={language} goal={profile?.goals?.[0]} />
      </section>

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
