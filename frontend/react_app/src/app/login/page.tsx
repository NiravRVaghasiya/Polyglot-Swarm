"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, m } from "motion/react";
import { useAuth } from "@/lib/auth";
import { Brand } from "@/components/ui/Brand";
import { Button } from "@/components/ui/Button";
import { ErrorNote } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { easeOut, fadeUp, spring, stagger } from "@/components/ui/motion";

type Mode = "login" | "register";

const MODES: { id: Mode; label: string }[] = [
  { id: "login", label: "Log in" },
  { id: "register", label: "Sign up" },
];

export default function LoginPage() {
  const { login, register } = useAuth();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(username, password);
      else await register(username, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <m.div
        variants={stagger(0.07)}
        initial="hidden"
        animate="show"
        className="w-full max-w-sm"
      >
        <m.div variants={fadeUp} className="mb-8 flex flex-col items-center gap-3 text-center">
          <Brand size="lg" />
          <p className="text-sm text-muted">Your multi-agent AI language tutor.</p>
        </m.div>

        <m.div variants={fadeUp} className="card p-5 sm:p-6">
          {/* Mode switch with a sliding pill */}
          <div
            role="tablist"
            aria-label="Account"
            className="mb-5 grid grid-cols-2 rounded-xl bg-surface2 p-1 text-sm font-semibold"
          >
            {MODES.map((m_) => {
              const active = mode === m_.id;
              return (
                <button
                  key={m_.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => {
                    setMode(m_.id);
                    setError(null);
                  }}
                  className={
                    "relative min-h-10 rounded-lg transition-colors duration-200 " +
                    (active ? "text-fg" : "text-muted hover:text-fg")
                  }
                >
                  {active ? (
                    <m.span
                      layoutId="auth-mode-pill"
                      transition={spring}
                      className="absolute inset-0 rounded-lg bg-surface shadow-card"
                    />
                  ) : null}
                  <span className="relative">{m_.label}</span>
                </button>
              );
            })}
          </div>

          <AnimatePresence mode="wait" initial={false}>
            <m.p
              key={mode}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0, transition: easeOut }}
              exit={{ opacity: 0, y: -6, transition: { duration: 0.15 } }}
              className="mb-4 text-sm text-muted"
            >
              {mode === "login"
                ? "Welcome back — pick up where you left off."
                : "Create an account to start practising."}
            </m.p>
          </AnimatePresence>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="username" className="field-label">
                Username
              </label>
              <input
                id="username"
                className="field"
                placeholder="Username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="password" className="field-label">
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  className="field pr-12"
                  type={showPassword ? "text" : "password"}
                  placeholder="Password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-xl text-muted transition-colors hover:text-fg"
                >
                  <Icon name={showPassword ? "eyeOff" : "eye"} size={18} />
                </button>
              </div>
            </div>

            <AnimatePresence>{error ? <ErrorNote key={error}>{error}</ErrorNote> : null}</AnimatePresence>

            <Button type="submit" size="lg" className="w-full" disabled={busy} loading={busy}>
              {mode === "login" ? "Log in" : "Sign up"}
              {!busy ? <Icon name="arrowRight" size={18} /> : null}
            </Button>
          </form>
        </m.div>
      </m.div>
    </main>
  );
}
