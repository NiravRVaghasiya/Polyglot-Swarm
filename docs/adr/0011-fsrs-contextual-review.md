# 0011. FSRS integration & contextual review with recall measurement (Phase 8)

- Status: Accepted
- Date: 2026-09-14

## Context

FSRS scheduling existed but review was display-only: a flat "what does X mean?"
prompt, no grading loop, and the learner model never saw whether a review
actually succeeded. The plan wants FSRS kept deterministic, a clean WHAT/WHEN
split (curriculum chooses what, FSRS chooses when), contextual review
generation, and — crucially — measurement of *actual recall* rather than
assuming the scheduler equals learning.

## Decision

Add `src/agents/review.py`, leaving `src/agents/srs.py` (the deterministic FSRS
functions) unchanged:

- `generate_contextual_review` embeds a due item in a short scenario-style
  retrieval cue via the fast tier, and falls back to a plain cue on any error so
  review always works offline.
- `grade_review` runs FSRS (`process_review_response`), persists the outcome
  (`record_review_outcome`), updates the recognition mastery dimension, emits a
  `REVIEW_RESULT` evidence event (strong, demonstrated-recall evidence), and
  updates the learner model immediately.

## Consequences

- The learner model is now updated from demonstrated recall, closing the loop
  the plan flagged (measure recall, don't assume it).
- FSRS stays deterministic and its public functions are unchanged; the
  WHAT/WHEN split is explicit.
- Contextual cues improve retrieval practice while degrading gracefully offline;
  richer scenario-embedded generation can build on this seam.
