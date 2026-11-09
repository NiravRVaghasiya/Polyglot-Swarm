# Polyglot Swarm — Web (React v2)

Production frontend: a Next.js (App Router) + Tailwind PWA that talks to the
Polyglot Swarm FastAPI backend.

## Features

- Username/password auth with bearer tokens (persisted to `localStorage`)
- Chat with the agent swarm, with scenario selection
- End-of-session report
- Progress dashboard: streak, words learned, CEFR, vocabulary-growth chart,
  and top grammar weaknesses
- Animated, tabbed dashboard (Today / Practice / Listening / Progress) with
  deep links (`/#practice`), light + dark themes, and skeleton loading states

## UI & motion

Motion uses [Motion](https://motion.dev) (`motion/react`) through `LazyMotion`
(components use the lightweight `m.*` elements) plus a few Tailwind keyframes.

- Shared timing tokens live in `src/components/ui/motion.ts`; keep new
  animations on them (150–400ms, ease-out entrances, spring presses).
- `MotionProvider` sets `reducedMotion="user"`, and `globals.css` neutralises
  CSS animations under `prefers-reduced-motion`.
- Colours are semantic tokens (`bg-surface`, `text-muted`, `bg-brand`, ...)
  defined as CSS variables in `globals.css` for both themes — avoid raw hex.
- Dashboard tab panels stay mounted when hidden, so switching tabs never drops
  a live chat session or a half-answered listening task.

## Setup

```bash
cd frontend/react_app
npm install
# Point at your running API (defaults to http://localhost:8000)
export NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev      # http://localhost:3000
```

## Testing

```bash
npm test         # vitest: API client hooks + auth guard
```

## Structure

```
src/
├── app/                 # Next.js App Router pages
│   ├── layout.tsx       # Root layout + AuthProvider
│   ├── page.tsx         # Protected home (auth guard -> /login)
│   └── login/page.tsx   # Login / signup
├── components/
│   ├── ChatPanel.tsx        # Scenario picker + chat + end-session report
│   ├── TodaysPlan.tsx       # Today's plan, CEFR profile, insights
│   ├── ListeningExercise.tsx# Listening tasks + per-kind results
│   ├── Onboarding.tsx       # First-run language + goal wizard
│   ├── ProgressDashboard.tsx# Stats, growth chart, weaknesses
│   └── ui/                  # Button, Card, Tabs, Icon, Brand, motion tokens
└── lib/
    ├── api.ts           # Typed API client (fetch + bearer token)
    ├── auth.tsx         # Auth context/provider + useAuth
    └── useProgress.ts   # Progress dashboard data hook
```

The API base URL is read from `NEXT_PUBLIC_API_URL` at build/runtime.
