"""Polyglot Swarm evaluation harness (Phase 18).

``benchmarks/`` (Phase 0) is a lightweight smoke-test harness: is the provider
layer alive, is structured output parseable, does the grammar policy hit a
false-correction-rate floor. It stays exactly as it is — this package does not
replace it.

``evals/`` is the fuller, versioned evaluation suite the plan calls for: one
subpackage per capability, each with its own labeled dataset and metrics, so a
model/prompt change can be checked against every capability it might affect,
not just a smoke test. Every suite is offline and deterministic (no live LLM
calls; agents' pure decision/scoring logic is exercised directly against
hand-labeled or seeded cases), so ``python -m evals`` runs the same way in CI,
locally, and air-gapped.

Layout::

    evals/
        harness.py      EvalResult + the suite runner (mirrors benchmarks/harness.py)
        grammar/        precision, recall, F1, false-correction rate, calibration
        vocabulary/     extraction precision/recall/F1
        assessment/     CEFR-vs-expert correlation, absolute error, calibration
        curriculum/     target coverage, skill balance, difficulty appropriateness
        regression/     runs every suite above and rolls them into one gate

Each suite's dataset lives in its own ``dataset.py`` as a versioned, hand-
labeled list of cases (a ``DATASET_VERSION`` constant marks changes) — the plan
calls for "datasets", and Python dataclasses are used rather than JSON/YAML data
files because several cases embed typed objects (``GrammarAnalysis``,
``PlanConstraints``) that would otherwise need a parallel schema just to
deserialize; the version constant gives the same traceability a data file would.

Run with::

    python -m evals
    POLYGLOT_DETERMINISTIC=1 python -m evals   # forces offline mode (irrelevant
                                                # here since no suite calls an
                                                # LLM, but kept for consistency
                                                # with `make eval`/CI)

Some plan metrics genuinely require a live model, a human rater, or
longitudinal outcome data this offline harness cannot produce (vocabulary
"sense accuracy"/"contextual appropriateness", curriculum "learner success
rate"). Each suite's docstring says explicitly which of its metrics are
measured here and which are out of scope, rather than faking a number.
"""
