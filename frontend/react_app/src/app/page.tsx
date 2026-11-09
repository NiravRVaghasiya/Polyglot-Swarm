"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { m } from "motion/react";
import { useAuth } from "@/lib/auth";
import { api, UserProfile } from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { ProgressDashboard } from "@/components/ProgressDashboard";
import { TodaysPlan } from "@/components/TodaysPlan";
import { ListeningExercise } from "@/components/ListeningExercise";
import { Onboarding } from "@/components/Onboarding";
import { Brand } from "@/components/ui/Brand";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { TabNav, TabPanel, type TabDef } from "@/components/ui/Tabs";
import { easeOut } from "@/components/ui/motion";

type TabId = "today" | "practice" | "listening" | "progress";

const TABS: readonly TabDef<TabId>[] = [
  { id: "today", label: "Today", icon: "sun" },
  { id: "practice", label: "Practice", icon: "chat" },
  { id: "listening", label: "Listening", icon: "headphones" },
  { id: "progress", label: "Progress", icon: "chart" },
];

const isTab = (v: string): v is TabId => TABS.some((t) => t.id === v);
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
  const [tab, setTab] = useState<TabId>("today");
  const [direction, setDirection] = useState(1);
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

  // Deep-linkable sections: /#practice, /#listening, ... Switching tabs
  // replaces the hash rather than pushing history, so Back still leaves the app.
  useEffect(() => {
    const fromHash = () => {
      const h = window.location.hash.slice(1);
      if (isTab(h)) setTab(h);
    };
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, []);

  const selectTab = useCallback(
    (next: TabId) => {
      if (next === tab) return;
      const from = TABS.findIndex((t) => t.id === tab);
      const to = TABS.findIndex((t) => t.id === next);
      setDirection(to > from ? 1 : -1);
      setTab(next);
      window.history.replaceState(null, "", `#${next}`);
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [tab],
  );

  const onOnboarded = useCallback((p: UserProfile) => setProfile(p), []);

  if (loading || !token || profileLoading) {
    return <ShellSkeleton />;
  }

  const needsOnboarding = !profile || profile.goals.length === 0;
  const language = profile?.target_languages?.[0];
  const goal = profile?.goals?.[0];

  const header = (
    <header className="flex items-center justify-between gap-3">
      <h1>
        <Brand />
      </h1>
      <Button variant="ghost" size="sm" onClick={logout}>
        <Icon name="logout" size={16} />
        Log out
      </Button>
    </header>
  );

  if (needsOnboarding) {
    return (
      <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
        {header}
        <Header onLogout={logout} />
        <Onboarding token={token} onComplete={onOnboarded} />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-5 px-4 pb-32 pt-4 sm:space-y-6 sm:p-6 sm:pb-12">
      {header}

      <m.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={easeOut}
        className="flex flex-wrap items-center gap-2 text-sm text-muted"
      >
        {language ? (
          <span className="chip bg-brand-soft text-link">
            <Icon name="globe" size={12} /> {language}
          </span>
        ) : null}
        {goal ? (
          <span className="chip bg-accent-soft text-accent">
            <Icon name="target" size={12} /> {goal}
          </span>
        ) : null}
      </m.div>

      <TabNav tabs={TABS} active={tab} onChange={selectTab} />

      <TabPanel id="today" active={tab === "today"} direction={direction}>
        <SectionTitle>Today</SectionTitle>
        <TodaysPlan token={token} language={language} goal={goal} />
      </TabPanel>

      <TabPanel id="practice" active={tab === "practice"} direction={direction}>
        <SectionTitle>Practice</SectionTitle>
        <ChatPanel token={token} />
      </TabPanel>

      <TabPanel id="listening" active={tab === "listening"} direction={direction}>
        <SectionTitle>Listening</SectionTitle>
        <ListeningExercise token={token} language={language} />
      </TabPanel>

      <TabPanel id="progress" active={tab === "progress"} direction={direction}>
        <SectionTitle>Progress</SectionTitle>
        <ProgressDashboard token={token} />
      </TabPanel>
    </main>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 text-lg font-bold tracking-tight sm:text-xl">{children}</h2>;
}

function ShellSkeleton() {
  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6" role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Skeleton className="h-9 w-9 rounded-xl" />
          <Skeleton className="h-6 w-40" />
        </div>
        <Skeleton className="h-8 w-20" />
      </div>
      <Skeleton className="h-14 w-full rounded-2xl" />
      <div className="space-y-3">
        <Skeleton className="h-32 w-full rounded-2xl" />
        <Skeleton className="h-48 w-full rounded-2xl" />
      </div>
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
