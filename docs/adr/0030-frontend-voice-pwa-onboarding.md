# 0030. Frontend voice, PWA, and onboarding (Gate E)

- Status: Accepted
- Date: 2026-09-15

## Context

The audit found Gate E (product) partially met: the React app rendered the
learner model (plan, skill map, progress) well, but three product
requirements were missing there. Voice worked only in the Gradio MVP, not the
React app; the "excellent mobile experience" was token PWA scaffolding (empty
manifest icons, no service worker, no viewport meta); and there was no
onboarding beyond a bare login form — a new user landed on an empty dashboard
with no language/goal captured.

## Decision

- **Voice as base64-JSON API endpoints, not multipart.** New
  `POST /api/v1/voice/transcribe` (audio → Whisper) and
  `POST /api/v1/voice/speak` (text → Edge TTS) carry audio as base64 in JSON.
  Rejected `multipart/form-data` because it would add a `python-multipart`
  dependency and break the uniform JSON `TestClient` testing every other route
  uses. Both endpoints are auth-scoped and return 503 (not 500) when the
  optional `voice` extra is absent, so the frontend degrades to text-only.
- **A `useVoice` hook + mic button in the existing chat.** `useVoice` records
  via `MediaRecorder`, base64-encodes the blob, calls `transcribe`, and can
  play a synthesized reply; it reports `supported=false` when the browser has
  no `MediaRecorder` so the button simply doesn't render. Rejected adding the
  unused `VoicePipeline`/LiveKit real-time path to the web app — a
  turn-by-turn cascade (record → STT → chat → optional TTS) is the right fit
  for a text-first tutor UI and reuses the existing chat flow.
- **A real PWA setup.** `layout.tsx` gains a Next-14/15 `export const viewport`
  (the app rendered at desktop width on phones without it), the manifest gets
  a populated icon and orientation, and `public/sw.js` is an app-shell service
  worker registered by a small client component. The service worker
  deliberately **never caches `/api/` traffic** (authenticated, must be fresh)
  and only caches navigations/static assets — a stale cached API response would
  be a correctness bug, not an offline nicety.
- **A first-run onboarding wizard.** `Onboarding` captures the two things the
  learner model most needs — target language and goal — and writes them to the
  profile; `page.tsx` shows it until a goal is set, then renders the dashboard
  and threads the chosen language/goal into the plan. Rejected a multi-step
  tour; the smallest wizard that makes the plan useful is the right amount of
  friction.
- **Wire the frontend into CI.** A new `frontend` CI job runs `tsc --noEmit`
  and `vitest`, and vitest tests were added for the new pieces, so the web app
  is actually gated rather than only the Python backend.

## Consequences

- The React app now has voice, an installable/offline-capable mobile
  experience, and guided onboarding — the Gate E items that were missing.
- **Verification caveat:** the development environment for this change had
  only a bundled `node` with no `npm`/`node_modules`, so `tsc --noEmit` and
  `vitest` could not be run here. The TypeScript and vitest tests were written
  against the existing `api.ts`/`auth.tsx`/component patterns and the plain-JS
  service worker was syntax-checked with `node --check`, but the frontend
  type-check and tests are verified by CI / a machine with `npm`, not by this
  change's own session. The Python voice endpoints are fully tested and
  passing.
- Voice quality still depends on the optional `voice` extra being installed
  server-side; without it the endpoints 503 and the UI stays text-only — an
  intentional graceful degradation, not a hard requirement.
