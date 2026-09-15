# 0021. Evaluation harness (Phase 18)

- Status: Accepted
- Date: 2026-09-14

## Context

`benchmarks/` (Phase 0/ADR-0002) gave the project a runnable, deterministic
smoke-test harness (`BenchmarkResult`, `all_benchmarks`, `python -m
benchmarks`), and two benchmarks already lived there: grammar precision/false-
correction-rate and verifier calibration. `benchmarks/__init__.py` said so
explicitly from the start: "Phase 0 provides the harness, not the full
evaluation datasets (those arrive with the Phase 18 evaluation suite)." The
plan calls for a fuller, versioned suite — one per capability (grammar,
vocabulary, assessment, curriculum, ...) with labeled datasets and metrics
(precision/recall/F1, calibration, correlation with expert ratings, absolute
error, target coverage, skill balance, difficulty appropriateness) — so that
"every model/prompt change runs evaluation" is a real, checkable statement
rather than an aspiration.

No shared home existed for precision/recall/F1 arithmetic — `benchmarks/
grammar_bench.py` computed TP/FP/FN by hand inline — though calibration
already had one (`src/evaluation/calibration.py`).

## Decision

- Keep `benchmarks/` exactly as it is; it stays the fast CI smoke check. Add a
  **separate** `evals/` package for the fuller suite rather than growing
  `benchmarks/` further, because evals are organized by capability with
  versioned datasets and (for curriculum) need isolated storage the benchmark
  harness never required.
- `evals/harness.py` mirrors `benchmarks/harness.py` deliberately:
  `EvalResult` (suite, name, passed, duration_ms, metrics, detail),
  `run_evals`/`all_evals`/`format_results`/`main`, the same "a failing case
  never crashes the run" policy, and lazy per-suite imports to avoid cycles.
  It adds one thing the benchmark harness didn't need: `isolated_storage()`, an
  async context manager that redirects `src.config.settings`' storage paths to
  a throwaway temp directory and cleans up afterward, for suites that exercise
  real SQLite-backed code (the curriculum planner).
- Add `src/evaluation/metrics.py`: `precision`, `recall`, `f1_score`,
  `false_positive_rate`, `PrecisionRecallResult`, `mean_absolute_error`,
  `pearson_correlation` — filling the gap `grammar_bench.py` had been
  papering over, without touching `calibration.py` (reused as-is).
- Four capability suites (`evals/{grammar,vocabulary,assessment,curriculum}`),
  each with a `dataset.py` (hand-labeled, versioned via a `DATASET_VERSION`
  string so a metrics regression can be traced to "the dataset changed" vs.
  "the policy changed") and a `suite.py` registering its evals. Every suite
  exercises real production code paths with no live model: `_select_errors`,
  `_parse_vocabulary_response`, `mastery_to_cefr`/`confidence_from`, and the
  real `plan_next_actions` planner (via `isolated_storage`).
- `evals/regression` rolls grammar+vocabulary+assessment into one pass/fail
  gate for a single CI signal, without curriculum (heavier, SQLite-backed;
  kept as its own explicit suite rather than folded into a lightweight gate).
- Each suite's module docstring states plainly which plan metrics are measured
  here and which are out of scope for an offline suite (e.g. vocabulary's
  "sense accuracy"/"contextual appropriateness" and curriculum's "learner
  success rate" need a live model, human rater, or longitudinal usage data —
  faking a number for these would be worse than admitting the gap).
- `python -m evals`, `make eval`, and a CI step alongside the existing
  benchmark step (not folded into `make check`/`ci`, matching how `benchmark`
  itself is a separate CI step rather than part of the local quality gate).

## Consequences

- A model/prompt change to grammar classification, vocabulary extraction,
  assessment mapping, or the curriculum planner now has an explicit,
  versioned, offline-runnable check with numeric pass/fail bars — not just the
  existing unit tests (which check specific input/output pairs, not aggregate
  precision/recall/calibration).
- Building real datasets surfaced three genuine issues that would otherwise
  have shipped: (1) an initial grammar-calibration eval paired
  confidence-of-classification with the wrong ground truth for non-error
  classifications; (2) an initial assessment dataset made every case "correct"
  by construction, so its calibration check was vacuous; (3) an initial
  curriculum skill-balance dataset didn't account for the planner's
  prerequisite gating and default action cap. All three were fixed at the
  dataset/eval level, not by loosening thresholds — the fixes are visible in
  `evals/grammar/suite.py`, `evals/assessment/dataset.py`, and
  `evals/curriculum/dataset.py`.
- `benchmarks/` and `evals/` now both exist with a clear division: benchmarks
  are the fast per-commit smoke check; evals are the fuller, dataset-driven
  suite for judging whether a model/prompt/policy change actually improved or
  regressed a capability.

