# 0032. Real-model evaluation framework

- Status: Accepted
- Date: 2026-11-06

## Context

Every existing quality check (`python -m evals`, `python -m benchmarks`)
scored *hand-written* model outputs against the agents' policies. Those
checks prove the pipeline is correct and deterministic, but they say nothing
about whether a real LLM detects learner errors, accepts valid variation,
returns valid structured output, or reports trustworthy confidence. An audit
also found four properties of the app's LLM layer that would corrupt a naive
real-model benchmark:

- `get_provider` fails over silently between providers, and resolves to the
  fake provider in deterministic mode.
- Providers returned only text: no token usage, and no model identity as
  reported by the provider.
- The production parser fills a missing `classification` with "wrong" and a
  missing `confidence` with 1.0, hiding malformed output.
- The grammar agent never sees the conversational situation, so register
  errors cannot be judged.

## Decision

1. **Separate package `evals/real/`, CLI `python -m evals.real`.** It is
   separate from the offline harness. CI runs only its offline parts (dataset
   validation, unit tests, strict typing). Real calls run on demand or from a
   scheduled, non-blocking workflow (`real-model-eval.yml`).
2. **Versioned, checksummed datasets with explicit provenance.** Cases are
   authored in YAML and built into group-hashed `dev` / `test` splits with a
   manifest of SHA-256 checksums. Each case records annotations,
   `validation_status` and its rubric version. The schema refuses
   `expert_validated` without an expert annotation. The first datasets are
   `author_labeled` (written by the AI assistant) and are reported as such.
3. **Concrete providers only.** The runner builds exactly the requested
   provider and model, probes availability (`not_configured`, `unreachable`,
   `auth_failed`, `model_not_found`, `timeout`, `error`), and never replaces an
   unavailable provider. Synthetic runs need `--allow-synthetic` and are
   labelled throughout.
4. **Production-identical calls, raw capture, offline scoring.**
   - `build_grammar_messages` / `build_vocabulary_messages` and the generation
     constants are extracted from the agents and shared with the runner.
   - `LLMProvider.generate_detailed` returns the reported token usage and
     model, with `generate` unchanged.
   - Every response is stored with its full prompt, and scoring replays the
     production parser, policy and evidence pipeline from the stored text.
5. **Metrics with denominators and intervals.**
   - Wilson intervals for proportions, and a seeded bootstrap for F1, ECE and
     paired differences.
   - Raw versus pipeline confidence calibration, with Platt and histogram maps
     fitted on dev only.
   - Exact McNemar for paired provider and prompt comparisons, and Cohen's κ
     for agreement.
   - Quality gates decided on the interval (pass, fail or inconclusive). The
     production gate is "not established" while the data is not
     expert-validated.
6. **Regression tracking.** Each run is recorded in `history.jsonl`.
   `compare` declares a regression only on a significant paired McNemar
   result, and refuses to compare across dataset versions or between synthetic
   and real runs.
7. **An experimental `grammar_context@1` prompt** is registered so the effect
   of supplying the situation can be measured. It is not wired into any agent.

## Consequences

- Benchmark numbers now come from real models, can be traced to their exact
  prompts, data and code, and can be re-scored without paying again.
- Results on `author_labeled` data are provisional. Expert annotation of the
  test split is the most valuable next step: the schema, rubric and gate logic
  already support it, and a dataset version bump will mark the change.
- With about 65 test cases, intervals are wide and many gates will be
  `inconclusive`. Making them decisive needs more data, not looser gates.
- Hosted providers (Claude, OpenAI, Gemini) could not be benchmarked in this
  environment because their configured keys are invalid. The runner records
  them as `auth_failed`, and the scheduled workflow can run them with valid
  secrets.
- Local models are slow on CPU-only hardware (about 1–2 minutes per call for
  an 8B model), which bounds how often a full local run is practical.
