# 0005. SQLite as source of truth, with a migration runner (Phase 2)

- Status: Accepted
- Date: 2026-09-14

## Context

Persistence was scattered: each store owned its own `CREATE TABLE IF NOT EXISTS`
DDL and `init_db()`, there was no schema version and no migration path, and the
learner profile lived only in JSON files. The plan (Phase 2) wants SQLite to own
users, profiles, sessions, turns, learner-state snapshots, evidence,
assessments, FSRS cards, analytics, experiments, and model runs, with safe
migrations, so a user can start a session, learn, quit, restart, authenticate,
resume, and receive a review generated from prior evidence.

## Decision

- Introduce a central schema owner, `src/memory/schema.py`, with an ordered
  migration runner keyed on SQLite's `PRAGMA user_version`. `init_all()` calls
  the existing per-store `init_db()` functions and then applies migrations, so
  there is one entry point that guarantees the full schema. Migrations are
  additive and safe (create tables/indexes); no automatic destructive changes.
- Add the missing canonical tables and thin stores: `profiles`, `sessions`
  (lifecycle + resume), `skill_states`, `learner_state_snapshots`, `evidence`,
  `assessments`, `experiments`/`experiment_assignments`, `model_runs`.
- Make SQLite the source of truth for learner profiles by having
  `user_profile` write through to a `profiles` table and read it first, while
  keeping the JSON file as a human-readable mirror (local-first).
- Record session lifecycle in `build_initial_state`/`persist_session`, and
  register the LLM telemetry sink to `model_runs` at API startup.

## Consequences

- Schema can evolve safely and idempotently; a clean DB and an upgraded DB
  converge to the same state.
- Learner state (profile, skills, assessments, evidence) is queryable and
  durable, unblocking the learner model (Phase 6) and evaluation (Phase 18).
- Keeping the JSON mirror preserves existing behavior/tests and the local-first
  story; SQLite is authoritative for reads.
- The pip-style single-file DB remains; no move to a server DB, consistent with
  self-hostability.
