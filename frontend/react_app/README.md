# Polyglot Swarm — Web (React v2)

Production frontend: a Next.js (App Router) + Tailwind PWA that talks to the
Polyglot Swarm FastAPI backend.

## Features

- Username/password auth with bearer tokens (persisted to `localStorage`)
- Chat with the agent swarm, with scenario selection
- End-of-session report
- Progress dashboard: streak, words learned, CEFR, vocabulary-growth chart,
  and top grammar weaknesses

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
│   └── ProgressDashboard.tsx# Stats, growth chart, weaknesses
└── lib/
    ├── api.ts           # Typed API client (fetch + bearer token)
    ├── auth.tsx         # Auth context/provider + useAuth
    └── useProgress.ts   # Progress dashboard data hook
```

The API base URL is read from `NEXT_PUBLIC_API_URL` at build/runtime.
