# 0006. Evidence pipeline: separating what happened from what we believe (Phase 3)

- Status: Accepted
- Date: 2026-09-14

## Context

The system updated its beliefs directly from raw LLM output: `persist_session`
collapsed each detected grammar error into the `error_patterns` counter and
upserted vocabulary straight from the vocabulary agent's parse. That loses the
underlying observations (no provenance, no confidence, no way to reproduce or
roll back a belief), and it conflates "what happened" with "what we believe" —
which the plan (Phase 3) calls out as the most important new subsystem.

## Decision

Introduce `src/evidence/`: every interaction emits immutable, structured
`LearningEvent` records (typed: `TURN_COMPLETED`, `GRAMMAR_ERROR`,
`VOCAB_PRODUCED`, `REVIEW_RESULT`, ...), each carrying skill, item, observed/
expected, an assessment, a confidence, and provenance (source component,
session, interaction, model version). Events flow through a pure
extract → normalize → deduplicate transform and are persisted (append-only,
idempotent on `event_id`) to the `evidence` table.

`persist_session` now emits and stores events **first**, then derives the belief
layer (vocabulary lexicon, grammar error taxonomy) *from* those normalized,
deduplicated events — never directly from the raw LLM output.

## Consequences

- Every learner-state change is explainable and reproducible; the belief layer
  is a projection of the evidence, enabling rollback and longitudinal analysis.
- Normalization (e.g. "Ser vs Estar" → `ser_vs_estar`) makes the grammar
  taxonomy aggregate correctly; deduplication prevents double-counting within a
  turn.
- The learner knowledge model (Phase 6) has a clean, typed input stream; it
  consumes events rather than reaching into agent output.
- `persist_session`'s return grows a `events` count; the existing
  vocabulary/grammar/turns counts are unchanged.
