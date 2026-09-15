# 0028. Experiment execution harness and published results (Gate C)

- Status: Accepted
- Date: 2026-09-15

## Context

A full audit against the plan's Definition of Done found Gate C (learning
evidence) still open after Phase 24, despite the pieces looking present. The
experiment *store* (`src/memory/experiments.py`: assignments, outcomes, the
`delayed_1d/7d/30d` measurement-point vocabulary, `summarize_outcomes`) and
the ablation *graph builder* (`src.orchestrator.graph.build_ablation_graph`,
arms A-E) both existed — but nothing joined them. Nothing outside tests called
`build_ablation_graph`; no code produced the delayed measurements the store
could record; and the plan's "published results" and "known limitations"
checkboxes were literally unchecked, because the only measured numbers the
repo produced (benchmarks/evals) were not assembled into any artifact and the
ablation comparison had never actually been run.

## Decision

- **An execution harness that joins builder to store.**
  `src/experiments/runner.py`'s `run_ablation_study` runs a scripted cohort of
  synthetic learners through each arm's compiled graph, persists each session's
  evidence via the normal lifecycle, measures a metric before and after, and
  records both to the outcomes store — producing an `AblationReport` of
  per-arm mean gain. This is the missing controlled comparison, runnable via
  `polyglot experiment ablation`.
- **A scripted tutor provider, because the fake provider proves nothing.**
  The deterministic `FakeProvider` returns empty analysis (no grammar errors,
  no vocabulary), so every arm would measure identically — a comparison with
  no signal. The runner therefore monkeypatches a small `_ScriptedTutorProvider`
  (realistic, still deterministic grammar/vocabulary output) into the agents
  for the duration of a run, so the arms that include the analysis pipeline
  (D/E) actually accumulate learner-model evidence and the ones that don't
  (A/B/C) don't. Rejected using a live model (non-reproducible, needs keys)
  and rejected leaving the fake provider (the comparison would be vacuous).
- **The metric is mean skill mastery, not the CEFR ordinal.** CEFR overall is
  a conservative *minimum* across skills that starts at an A2 fallback, so a
  single scripted session moves it confusingly (a forced grammar error can
  push it *down*). Mean mastery over grammar+vocabulary is a clean, monotone
  signal: A/B/C gain +0.000, D/E gain +0.333. The CEFR band is kept in each
  outcome's payload for reference. Rejected the ordinal as the primary metric
  precisely because it made the ablation's result read backwards.
- **A delayed-retention producer, not just a schema.**
  `experiments.due_measurements` computes which `delayed_*` points are due
  (assignment time + a fixed offset, minus points already recorded) and
  returns a work list, so a scheduled job (or `polyglot experiment due`) can
  drive real delayed measurement. Rejected leaving the points as a
  vocabulary of strings with no producer, which is exactly what the audit
  flagged.
- **A reproducible results artifact generator.**
  `src/experiments/results.py` + `polyglot results` run all three harnesses
  deterministically and write `docs/results.md` with the actual numbers and a
  Known Limitations section kept *in code* (so it regenerates with the numbers
  and cannot drift). The generator refuses to run unless
  `POLYGLOT_DETERMINISTIC=1`, making "reproducible" an enforced property
  rather than a claim.

## Consequences

- Gate C's "controlled comparison", "ablation study", "published results",
  and "known limitations" are now real: a single command runs the comparison
  and writes a numbers-backed artifact, and the delayed-retention machinery
  has a producer end to end.
- The honesty is built in: `docs/results.md`'s limitations section states
  plainly that the numbers are deterministic-mode (fake/scripted provider,
  not live-model quality), that the ablation is a wiring/attribution result
  rather than a human-learning-gains claim, and that no real longitudinal
  study has been run. Reaching a *validated* learning claim still requires a
  study with real learners over real calendar time — the harness makes that
  study runnable, it does not substitute for it.
- The ablation runner reuses the real graph/lifecycle rather than a bespoke
  mock loop, so a topology or evidence-pipeline change is reflected in the
  comparison automatically — at the cost of the runner depending on those
  internals (mitigated by it living in its own package with its own tests).
