# 0017. Multi-signal adaptive difficulty controller (Phase 14)

- Status: Accepted
- Date: 2026-09-14

## Context

Adaptive difficulty reacted to a single evaluator signal derived only from
grammar error rate ("more correct → harder"). The plan wants difficulty to
respond to multiple signals — accuracy, response latency, repair frequency,
lexical diversity, complexity, comprehension, fatigue — via a difficulty
controller, not a monotonic rule.

## Decision

- Add `src/agents/difficulty_signals.py`: `extract_signals` computes accuracy
  (error rate), lexical diversity (type/token), average response length, and
  repair frequency (self-correction markers) from the learner's turns;
  `assess_difficulty` aggregates weighted votes into
  `too_easy`/`appropriate`/`too_hard`, requiring a couple of turns of evidence
  before moving.
- `combine(evaluator, controller)` reconciles the two signals safety-first: any
  `too_hard` wins (learner comfort), otherwise a `too_easy` from either raises
  difficulty. `adaptive_node` uses this blend while keeping its
  `{cefr_level, current_scenario}` return and attaching `difficulty_signals`
  for observability.

## Consequences

- The controller catches struggle the error-rate heuristic alone would miss
  (short answers + frequent repairs → back off even with few flagged errors).
- Per-turn latency is not yet captured in state, so it is omitted for now; the
  signal set can grow (latency, comprehension) without changing callers.
- The scoring is transparent and rule-based; a learned controller can replace
  `assess_difficulty` behind the same interface later.
