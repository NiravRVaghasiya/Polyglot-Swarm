# 0008. Multi-dimensional vocabulary mastery and collocations (Phase 5)

- Status: Accepted
- Date: 2026-09-14

## Context

Vocabulary was modeled as effectively known/unknown, with only aggregate
correct/incorrect counters and an FSRS card. But knowing a word's meaning
(recognition) is not the same as being able to produce it, hear it, or spell it,
and much competence lives in multi-word collocations. The plan (Phase 5) wants
recognition/production/listening/spelling tracked separately, plus register,
frequency, production history, and collocations as first-class objects.

## Decision

- Add per-word mastery dimensions (`recognition`, `production`, `listening`,
  `spelling`) and lexical metadata (`register`, `frequency_rank`, `first_seen`,
  `first_produced`, `successful_productions`, `failed_productions`) to the
  `vocabulary` table via a v3 migration that is additive and idempotent (works
  on fresh and existing databases; guarded `ALTER TABLE ADD COLUMN`).
- Update dimensions with a transparent EMA-style rule (`record_dimension`) and
  set metadata (`set_metadata`); `persist_session` bumps the production
  dimension per produced word and stamps `first_seen`.
- Model collocations as first-class objects in a new `collocations` table/store,
  tracked and scheduled like vocabulary.

## Consequences

- The learner model and FSRS can reason about *which aspect* of a word is weak,
  not just whether it is "known".
- Migrations stay safe/additive; existing vocabulary rows gain defaulted
  columns without data loss.
- Frequency lists and collocation corpora remain to be populated (greenfield);
  the schema and store are ready for them.
