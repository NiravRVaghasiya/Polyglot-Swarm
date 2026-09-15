# 0022. Learning science experiment platform (Phase 19)

- Status: Accepted
- Date: 2026-09-15

## Context

Phase 2 already shipped `experiments`/`experiment_assignments` tables and a
minimal registry (`src/memory/experiments.py`: `create_experiment`/`assign`/
`get_assignment`) — deterministic, stable variant assignment per user. What
was missing was everything the plan's actual experiment design needs: a way to
record measured *outcomes* at each point in a study (pre-test, intervention,
immediate post-test, 1/7/30-day delayed tests), and a way to build the
ablation arms it calls out (A: conversation only .. E: full system) to learn
which architectural components actually create learning value.

Two design questions had to be resolved:

1. **What counts as a "test"?** Building a separate assessment instrument
   would duplicate work — the multidimensional CEFR profile
   (`src.assessment.build_cefr_profile`, Phase 12) is already a point-in-time,
   snapshot-able measurement of a learner's competence.
2. **How do you get a "conversation-only" arm** when the production graph
   (`src.orchestrator.graph.build_graph`) hardcodes the full
   conversation→grammar/vocabulary/cultural→evaluator fan-out?

## Decision

- Extend `src/memory/experiments.py` with `record_outcome`/`get_outcomes`/
  `summarize_outcomes` over a new `outcomes` table (migration 0005):
  `(experiment, user_id, variant, measurement_point, metric, value, payload)`.
  `record_outcome` defaults `variant` to the user's existing assignment so
  callers measuring an already-assigned user don't have to look it up
  separately. `value` is a single float (e.g. a CEFR-band ordinal) so
  cross-user aggregation stays simple; richer detail rides in `payload`.
  `MEASUREMENT_POINTS` documents the plan's six points as a naming
  convention (not a DB constraint, for forward compatibility).
- Reuse the CEFR profile as the measurement instrument: `polyglot experiment
  measure` snapshots `build_cefr_profile` and records the overall band's
  ordinal (A1=0..C2=5) as the outcome, with the full profile in `payload`. No
  new "test" instrument was built.
- Add an optional `components: frozenset[{"analysis", "review"}] | None`
  parameter to `build_graph`, defaulting to `None` (= every component, i.e.
  the exact graph that existed before this parameter was added — no behavior
  change for any existing caller). `"analysis"` gates the grammar/vocabulary/
  cultural/evaluator fan-out; `"review"` gates the FSRS review node and the
  router's review branch. `ABLATION_ARMS` spells out the plan's five arms as
  which components each includes, and `build_ablation_graph(arm)` is a thin,
  self-documenting wrapper. Arms A and B share the same topology (memory/
  persistence is not a graph-wiring concern — it happens in
  `src.orchestrator.lifecycle` regardless of which nodes ran).
- Add `polyglot experiment create/assign/measure/report` CLI commands
  following the existing `@app.command()` pattern, grouped under an
  `experiment` sub-Typer app since they are a distinct, less-frequent concern
  from the day-to-day learner-facing commands.

## Consequences

- A controlled comparison (e.g. adaptive tutor vs. generic conversation) can
  now be run end-to-end: assign a variant, measure outcomes at each study
  point via the existing CEFR profile, and summarize means by variant/point —
  without building a parallel assessment system.
- The five-arm ablation ladder is a one-line call
  (`build_ablation_graph("A")` .. `("E")`) rather than five hand-maintained
  copies of the graph-building code, and stays automatically in sync with the
  production graph's node implementations.
- `model_runs`/`evidence` collected during an ablation-arm session behave
  exactly as they do in production (same telemetry, same observability), so
  an ablation study's cost/latency data is directly comparable to production
  data.

