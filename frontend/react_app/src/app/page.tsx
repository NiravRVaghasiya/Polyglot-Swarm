"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api, UserProfile } from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { ProgressDashboard } from "@/components/ProgressDashboard";
import { TodaysPlan } from "@/components/TodaysPlan";
import { ListeningExercise } from "@/components/ListeningExercise";
import { Onboarding } from "@/components/Onboarding";
import { PrivacyPanel } from "@/components/PrivacyPanel";

function Header({ onLogout }: { onLogout: () => void }) {
  return (
    <header className="flex items-center justify-between">
      <h1 className="text-xl font-bold sm:text-2xl">🌍 Polyglot Swarm</h1>
      <button className="rounded-md px-2 py-1 text-sm text-slate-500 hover:bg-slate-100" onClick={onLogout}>
        Log out
      </button>
    </header>
  );
}

export default function HomePage() {
  const { token, loading, logout } = useAuth();
  const router = useRouter();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  // Bumped when the learner model changes (a session ends, answers are
  // scored), so the plan and progress views fetch again.
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

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
      <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
        <Header onLogout={logout} />
        <Onboarding token={token} onComplete={onOnboarded} />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-8 p-4 sm:p-6">
      <Header onLogout={logout} />

      <section>
        <h2 className="mb-2 text-lg font-semibold">Today</h2>
        <TodaysPlan
          token={token}
          language={language}
          goal={profile?.goals?.[0]}
          refreshKey={refreshKey}
        />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Practice</h2>
        <ChatPanel token={token} onSessionEnd={refresh} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Listening</h2>
        <ListeningExercise token={token} language={language} onSubmitted={refresh} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Progress</h2>
        <ProgressDashboard token={token} refreshKey={refreshKey} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Your data</h2>
        <PrivacyPanel token={token} onDeleted={logout} />
      </section>
    </main>
  );
}
