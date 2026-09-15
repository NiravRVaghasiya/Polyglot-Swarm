# 0009. Learner Knowledge Model & mastery engine (Phase 6)

- Status: Accepted
- Date: 2026-09-14

## Context

Phases 2-3 gave us persistent skill-state storage and an evidence stream, but
nothing turned evidence into a maintained belief about the learner. The plan
calls the persistent computational model of the learner the strongest
differentiator, and says a robust weighted-evidence model is enough for MVP —
the important part is the *interface*, not premature Bayesian/IRT complexity.

## Decision

Create `src/learner/`:

- `mastery_engine.py` — a pure function from (prior belief, evidence batch) to
  (posterior mastery, uncertainty). Each event's `assessment` maps to a signal
  in [0, 1], weighted by its confidence; the belief moves toward the signal by
  an amount that shrinks as evidence accumulates. Acceptable-variation
  assessments (regional/informal/...) are near-neutral, never a learner gap.
- `uncertainty.py` — uncertainty decays with (confidence-weighted) evidence.
- `skill_graph.py` — skill/construction prerequisite relations + readiness.
- `knowledge_model.py` — the facade: read/write `skill_states`, update from
  evidence, and snapshot to `learner_state_snapshots`.

`persist_session` updates the model from each session's events and snapshots it.
The engine is pure and swappable (BKT/IRT/DKT later) without touching callers.

## Consequences

- The system now maintains an accurate, uncertainty-aware, per-skill model of
  the learner — the input the Next-Best-Learning-Action planner (Phase 7)
  needs.
- Belief changes are explainable (derived from stored evidence) and reversible
  (snapshots), consistent with the evidence-first architecture (ADR-0006).
- The MVP scoring is deliberately simple; the interface is stable so the model
  can be upgraded without a rewrite.
