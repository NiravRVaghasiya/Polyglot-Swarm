# 0016. Scenarios as pedagogical environments (Phase 13)

- Status: Accepted
- Date: 2026-09-14

## Context

Scenarios were persona + objectives + per-objective required vocab. The plan
wants them to be pedagogical *environments* that deliberately create
opportunities for target skills: they should declare the grammar, vocabulary,
and communicative functions to elicit, the constraints to honor, the conditions
that count as failure, and the cross-language transfer opportunities they
surface — and the session should report whether the learner met the scenario's
goals.

## Decision

- Add optional fields to the `Scenario` model (`target_grammar`,
  `target_vocabulary`, `target_functions`, `constraints`, `failure_conditions`,
  `transfer_opportunities`). Pydantic ignores unknown keys, so existing YAML
  keeps parsing; adding optional fields is backward-safe.
- Expose these in `build_scenario_context` and thread them into the
  Conversation Agent's prompt as a subtle "pedagogical steering" block that
  makes the persona create opportunities for the targets (without naming grammar
  to the learner).
- Extend `evaluate_success` with `failed`/`failure_reasons` (deterministic
  failure-condition checks, e.g. switched-to-English), and surface a
  scenario-outcome section in the session report.
- Seed the new fields into representative scenarios.

## Consequences

- Conversations become intentional practice environments, not just role-play.
- Scenario outcomes are visible, feeding progress and the curriculum planner.
- Failure-condition checks are simple heuristics for now; an LLM check can be
  added later for free-text conditions without changing the interface.
