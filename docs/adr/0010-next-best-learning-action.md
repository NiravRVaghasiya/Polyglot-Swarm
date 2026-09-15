# 0010. Next Best Learning Action / curriculum planner (Phase 7)

- Status: Accepted
- Date: 2026-09-14

## Context

The system could model the learner (Phase 6) but every interaction was still an
undifferentiated conversation. The plan calls the Next Best Learning Action the
strategic heart of the product: given what the learner can and cannot do, what
is due, their goal, and their time/energy, choose the highest-value next action
(argmax Expected Learning Value under constraints).

## Decision

Add `src/curriculum/`:

- `actions.py` — a typed vocabulary of learning actions (continue_conversation,
  review_vocab, target_grammar, contrast_two_forms, ...), each explainable
  (carries a `reason`) and estimable (`priority`, `estimated_minutes`).
- `constraints.py` — `PlanConstraints` (time, fatigue, goal, max actions) with
  goal→skill weighting and a fatigue penalty.
- `difficulty.py` — desirable-difficulty (value peaks in the optimal-challenge
  zone) plus an uncertainty bonus (practising uncertain beliefs improves the
  model).
- `objectives.py` — the Expected Learning Value scoring function.
- `planner.py` — reads the learner model, FSRS-due reviews, and grammar
  weaknesses; scores, ranks, and packs candidates into the time budget.

The planner is pure and deterministic (no LLM), so plans are fast, reproducible,
and fully explainable. Shipped CLI-first (`polyglot plan`) with no graph/state
changes, so it can be wired into the graph/API later.

## Consequences

- Every interaction can now be intentional, and recommendations are explainable.
- The WHAT/WHEN split with FSRS (ADR-0011) is respected: the planner chooses
  what to practise; FSRS supplies what is due.
- ELV scoring is intentionally simple and transparent; it can be replaced with a
  learned policy later without changing the action/constraint interfaces.
