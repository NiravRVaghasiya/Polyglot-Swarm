# 0019. Learner-model API and frontend (Phase 16)

- Status: Accepted
- Date: 2026-09-14

## Context

By Phase 15 the learner model was rich — a curriculum planner (Phase 7), a
multidimensional CEFR profile (Phase 12), and a per-skill knowledge model
(Phase 6) — but none of it was reachable from outside a Python process. The
plan's product goal is for a learner to be able to answer "what should I
practise today, and why?" from the actual product surface (the React app), not
from a REPL. That requires: typed REST endpoints over the existing pure
(no-LLM) query functions, and frontend code that renders them.

## Decision

- Add `src/api/routes/learner_routes.py` under `/api/v1/learner`, auth-scoped
  via the existing `get_current_user` dependency, with one endpoint per
  existing query function rather than a new aggregate query layer:
  - `GET /plan` → `curriculum.plan_next_actions`
  - `GET /cefr` → `assessment.build_cefr_profile`
  - `GET /skill-map` → `learner.get_knowledge_model().current_beliefs`
  - `GET /cefr-history` → `memory.progress.cefr_progression`
  - `GET /insights` → a composition of the above three, adding the weakest
    skills and top recommended-focus reasons — the one endpoint that is new
    synthesis rather than a direct passthrough.
- Add explicit Pydantic response models (`PlanResponse`, `CEFRProfileResponse`,
  `SkillMapResponse`, `InsightsResponse`, ...) in `src/api/schemas.py` instead
  of returning raw dicts, so the frontend gets a stable, typed contract
  (`SkillAssessmentResponse.skill` is optional since it duplicates the dict key
  in `CEFRProfileResponse.skills`).
- Extend the React client (`api.ts`) with one function per endpoint, add a
  `usePlan` hook that fetches plan/CEFR/insights together via `Promise.all`,
  and a `TodaysPlan` component rendering ranked actions with their reasons, a
  CEFR skill-map bar chart, and the insights summary on the home page.

## Consequences

- Every new route is a thin wrapper over an already-tested pure function, so
  route tests only need to check status codes, auth, and shape — the actual
  planning/assessment logic is covered by its own unit tests.
- The frontend now has a typed contract to code against; a future change to a
  response shape is a visible TypeScript error rather than a silent runtime
  mismatch.
- `usePlan.test.tsx` was written to mirror the existing `useProgress.test.tsx`
  pattern but could not be executed in this environment (no `node_modules`);
  it should be run in CI/locally where the frontend toolchain is installed.

