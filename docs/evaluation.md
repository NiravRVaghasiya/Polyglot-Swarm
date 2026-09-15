# Evaluation

Two distinct things share the name "evaluation" in this codebase: the
**evaluator agent** (a graph node that QAs every turn's grammar/cultural
output before it reaches the learner model) and the **evaluation harness**
(offline benchmarks/evals that measure the system, not a live turn). This
document covers both.

## The evaluator agent

`src/agents/evaluator.py`'s `evaluator_node` runs after the
grammar/vocabulary/cultural agents (a graph fan-in), and does four things:

1. **Fast heuristic difficulty check** — `_assess_difficulty()` is a pure
   error-rate calculation, no LLM call: error rate > 0.5 → `"too_hard"`,
   < 0.05 with more than 3 turns → `"too_easy"`, else `"appropriate"`.
2. **Early exit** — if there is nothing to validate (no grammar errors, no
   cultural notes), the heuristic result is returned immediately. No LLM call
   is made for a clean turn.
3. **Budget-aware tier selection** — see below.
4. **LLM QA pass** — calls the provider (`json_mode=True`) with the
   `evaluator.jinja2` prompt, tolerantly parses the JSON response
   (`_parse_evaluation`, stripping code fences), and passes the result to the
   verifier.

A failed LLM call here (any exception) never breaks the turn: the evaluator
falls back to an empty `overrides`/`decisions` payload, and the verifier
falls back to the errors' own stored confidence.

### Budget-aware tier escalation

`src/evaluation/policies.py`'s `is_high_impact(error)` returns true when an
error's `classification` is `wrong` or `awkward` **and** its `severity` is
`critical` or `moderate`. The evaluator uses the costlier `"primary"` tier
only when *any* grammar error in the turn is high-impact; otherwise it uses
`"fast"`. This is a direct cost/latency optimization (Phase 22): most turns
have no error, or only a minor one, and don't need the stronger model's
judgment to QA them.

## The verifier: accept / revise / abstain

`src/evaluation/verifier.py`'s `verify_errors()` is pure and deterministic —
no LLM call of its own. For each candidate grammar error it resolves a
`Decision`:

- From the evaluator LLM's structured per-index decision, if present.
- Otherwise, falls back to `src.evaluation.policies.decide(confidence)` using
  the error's own stored confidence.

Thresholds (`policies.py`): `ABSTAIN_THRESHOLD = 0.5` — below this, the
decision is always `ABSTAIN` (the correction is suppressed rather than shown,
on the principle that a false correction is worse than a missed one).
`ACCEPT_THRESHOLD = 0.75` exists as a named constant but `decide()` doesn't
branch on it directly today — above the abstain floor, the decision is
`REVISE` if the LLM offered a revision, else `ACCEPT`.

**Register conflicts** between a grammar correction and a cultural note (via
`src.evaluation.conflict.reconcile_grammar_culture`) become a forced drop
regardless of what the LLM decided — e.g. don't "correct" an informal form
the cultural agent has already flagged as contextually appropriate.

The verifier's output tracks `kept` (accepted/revised errors),
`dropped_indices`, an `abstained` count, and a `revised` count — abstention
is a first-class, counted outcome, not silently indistinguishable from a
miss.

## Calibration

`src/evaluation/calibration.py` is an **offline measurement tool**, not
something the runtime branches on. `reliability_buckets()` bins
`(confidence, correct)` pairs into equal-width buckets; `calibration_error()`
computes the sample-weighted Expected Calibration Error across buckets — the
question it answers is "of the corrections the verifier was 90% sure about,
were about 90% actually right?" `benchmarks/calibration_bench.py` runs this
against a labeled prediction set and asserts ECE stays under a threshold.

## The evaluation harness (offline)

Distinct from the evaluator agent above: `evals/harness.py` (shape mirrors
`benchmarks/harness.py`) runs suites from `evals.{grammar, vocabulary,
assessment, curriculum, regression}`, aggregating `EvalResult`s. One failing
eval does not stop the run — `all_evals()` executes every suite and reports
all results. Every suite uses `harness.isolated_storage()`, which redirects
`settings.data_dir`/`db_path`/`profiles_dir`/`chroma_path` to a temp
directory, so running evals never touches real `./data`.

Run it with:

```bash
make eval
# equivalent to:
POLYGLOT_DETERMINISTIC=1 python -m evals
```

`make benchmark` (`python -m benchmarks`) is the sibling harness for
performance/quality benchmarks (including the calibration benchmark above)
rather than correctness regressions.
