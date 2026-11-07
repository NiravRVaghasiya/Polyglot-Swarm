# Real-model evaluation

This page covers how Polyglot Swarm measures whether *real* LLMs assess
learner language correctly. It explains what the framework does, what the
datasets are and are not, how each metric is defined, and what the first real
runs found. The decision record is [ADR-0032](adr/0032-real-model-evaluation.md).

## Why a separate framework

`python -m evals` and `python -m benchmarks` are offline and deterministic.
They score *hand-written* model outputs, so they test the agents' policies and
the pipeline, but not whether a real model produces those outputs. The
real-model evaluation lives in `evals/real/` and is run with
`python -m evals.real`. It:

- sends the **exact production prompts and parameters** (the agents'
  `build_grammar_messages` / `build_vocabulary_messages`, temperature 0, and
  700 / 500 max tokens) to **concrete providers**;
- never goes through the failover router. A result labelled `claude` cannot
  have come from Gemini, and the deterministic fake provider runs only with
  `--allow-synthetic`, which stamps the whole run `synthetic`;
- **preserves every raw response** with its full prompt, parameters, reported
  model, token usage, latency, attempts and errors, so scoring can be redone
  without new model calls;
- scores responses through the **production code paths**: `parse_structured`
  → `_select_errors` → `build_events`. This measures what a learner would get
  and what the learner model would record, not a lenient re-parse.

Only the offline parts run in CI (`python -m evals.real validate`, the unit
tests under `tests/test_evals_real/`, and `mypy --strict evals/real`). Real
calls run on demand, or weekly via `.github/workflows/real-model-eval.yml`.

## Layout

```
evals/real/
  schema.py        versioned case / annotation / manifest schemas (SCHEMA_VERSION)
  datasets.py      build splits from source.yaml, checksum, leakage checks
  datasets/
    RUBRIC.md      labeling rubric (grammar-rubric-1.0, vocabulary-rubric-1.0)
    grammar/source.yaml               authored cases (edit here)
    grammar/grammar-2026.11.0/        published dev.jsonl, test.jsonl, manifest.json
    vocabulary/...
  config.py        EvalConfig (versioned; hashed into every run) + quality gates
  configs/*.json   default, context-variant, context-variant-dev
  providers.py     concrete provider construction + availability probe
  runner.py        plan calls, execute with timeout/retry, record, resume
  scoring.py       per-case outcomes (pure)
  metrics.py       aggregation with denominators and 95% intervals
  report.py        report.json + report.md, gates, completeness
  regression.py    history.jsonl + paired regression comparison
  runs/<run_id>/   manifest.json, responses.jsonl, report.json, report.md
src/evaluation/statistics.py   Wilson, bootstrap, McNemar, kappa, Brier, AURC,
                               Platt / histogram calibration, interval-based gates
```

## Datasets

| Dataset | Version | Cases | dev / test | Languages |
|---|---|---|---|---|
| grammar | `grammar-2026.11.0` | 98 | 33 / 65 | Spanish 52, Italian 14, French 14, German 12, Polish 6 |
| vocabulary | `vocabulary-2026.11.0` | 14 | 3 / 11 | Spanish 7, Italian 3, French 2, German 2 |

Grammar cases fall into ten categories: correct, incorrect, vocabulary misuse,
context-inappropriate register, acceptable alternative (including synonyms),
regional/dialect, formal, informal, ambiguous, and adversarial (prompt
injection and misleading claims). Each case also records the learner's CEFR
level (A1–C1) and how hard it is to judge (easy, medium or hard). An error case
lists every accepted correction and construction id. An error-free case lists
the taxonomy labels a model may legitimately use for it (for example
`regional` for voseo) and the alternative formulations that are also correct.
Ambiguous cases have `has_error: null`; for them, abstaining is the right
answer.

### Provenance and its limits

**No case is expert-validated.** I wrote and labelled every case (the
repository's AI assistant, `claude-opus-5-5`) on 2026-11-06, under the rubric
in `datasets/RUBRIC.md`. Every case therefore carries
`validation_status: author_labeled`. The schema refuses `expert_validated`
unless an annotation comes from an `expert` or `trained_annotator`. Reports read
this field, and the quality-gate section says gates are provisional while any
case is not expert-validated. Further limits:

- There is a single annotator, so inter-annotator agreement cannot be computed
  yet. The schema stores multiple annotations per case so it can be added.
- The annotator is itself an LLM, which may share blind spots with the models
  under test.
- Some labels are defensible both ways. Those are marked `ambiguous` (for
  example laísmo, or the Italian indicative after *penso che*) rather than
  forced. I also replaced one case during authoring: *libreria* also means
  bookcase, so the original sentence had no error.

### Splits and leakage

A case's split is a function of its `group_id` only:
`sha256("polyglot-real-eval-split-v1:" + group_id)`, with the first 32 bits
below 0.3 going to `dev`. Variants of one item, such as a minimal pair or the
same sentence with an adversarial prefix, share a group, so they never
straddle splits. `dev` is for prompt development and for fitting calibration
maps. `test` is held out, and benchmark numbers are reported on it. There is
no training split, because nothing is trained.

`python -m evals.real validate` and the dataset tests check that:

- the published files are byte-identical to what `source.yaml` builds;
- every file's SHA-256 matches the manifest;
- no group or normalized text appears in both splits;
- no test text appears in any prompt template.

## Metric definitions

Quality metrics are computed only over calls that **succeeded**. Failed calls
(timeouts, provider errors) count as execution failures, never as "no error
found". A response that is not valid for the production schema *is* scored,
because production treats it as "no errors"; the structured-output metrics
show how often that happens. Each proportion is reported as value, numerator,
denominator and 95% Wilson interval.

### Grammar detection

Detection is scored per case. Ambiguous cases are excluded from these metrics
and measured separately.

| Metric | Definition | Denominator |
|---|---|---|
| precision | TP / (TP + FP) | cases where an error was surfaced |
| recall | TP / (TP + FN) | cases labelled as containing an error |
| false_correction_rate | FP / (FP + TN) | cases labelled error-free |
| missed_error_rate | FN / (TP + FN) | cases labelled as containing an error |
| localization_rate | true detections whose surfaced span matches an expected span | TP |
| span_precision / span_recall | span matches / surfaced errors; matched expected / expected errors | all surfaced / all expected |
| correction_accuracy, construction_accuracy | the matched error's correction / construction id is an accepted one | surfaced errors that match an expected span |
| acceptable_alternative_recognition, synonym_recognition, dialect_acceptance, register_acceptance | not flagged | error-free cases of that category |
| register_label_agreement | the model reported the deviation with an accepted label (e.g. `informal`) | formal / informal cases |
| context_inappropriate_recall, vocabulary_misuse_recall | flagged | error cases of that category |
| ambiguous_abstention_rate | nothing surfaced | ambiguous cases |
| adversarial_accuracy | detection correct | adversarial cases |

Matching works as follows:

- **Spans** match when their normalized forms contain each other or have a
  token Jaccard of at least 0.5.
- **Corrections** match when an accepted correction appears in the model's
  correction (or the reverse).
- **Constructions** match when the normalized ids are equal or contain each
  other.

This is lexical matching, not a semantic judgment. It can under-credit a
correct but differently worded correction.

### Structured output

Rates are per successful call unless the entry denominator is noted.

- `schema_valid_rate` — the production parser accepted the response.
- `json_valid_rate` — the response was parseable JSON at all.
- `bare_list_rate` — the top level was a JSON array instead of
  `{"errors": [...]}`.
- `recoverable_rate` — of the schema-invalid responses, the share a wrapper
  could have recovered.
- `missing_field_rate`, `invalid_field_rate`, `unsupported_assessment_rate` —
  per **entry**. `unsupported_assessment_rate` counts entries whose
  classification is outside the taxonomy.

The production parser hides missing fields: a missing `classification`
becomes "wrong" and a missing `confidence` becomes 1.0.

### Evidence extraction

The surfaced errors are passed through `build_events`, and the resulting
events are graded:

- precision and recall against the expected errors;
- **skill** accuracy, which shows that every grammar-agent finding is filed as
  `grammar`, including vocabulary misuse and pragmatics;
- **subskill** accuracy (construction id);
- **difficulty** — how often it is known, which only happens for
  constructions in a language pack, and how often it agrees with the labelled
  CEFR;
- **duplicates** — duplicate events remaining after the pipeline, and the
  distinct errors recovered in cases with two errors of the same kind.

### Vocabulary extraction

All rates are over successful calls.

| Metric | Definition | Denominator |
|---|---|---|
| precision | extracted words that are required or optional | extracted words |
| recall | required words extracted | required words |
| forbidden_rate | extracted words the prompt forbids (names, numbers, basic words) | extracted words |
| translation_accuracy | the gloss matches an accepted translation (lenient lexical match) | required words found |
| produced_vs_exposed_accuracy | the production extractor's `VOCAB_PRODUCED` vs `VOCAB_OBSERVED` decision is right | required words found |
| nothing_to_extract_clean | nothing was extracted | cases with no required words |

### Calibration and abstention

- **Prediction set:** every proposed deviation classified `wrong` or
  `awkward`, on cases that are not ambiguous. It counts as *correct* when the
  case contains an error and the deviation localizes it.
- **Raw versus pipeline confidence:** raw LLM confidence is the number in the
  JSON, or *missing*. Pipeline (evaluator) confidence is what the learner
  model receives: the raw value, or the schema default 1.0 when it is missing.
- **Reported for each:** ECE (10 equal-width bins) with a bootstrap interval,
  the Brier score, a reliability table, the risk–coverage curve, AURC, and the
  number of distinct confidence values. A model that always says 1.0 cannot
  rank its own predictions.
- **Fitted calibration:** Platt and histogram-binning maps are fitted on the
  **dev** run only and evaluated on **test**. They are fitted only when dev has
  at least 15 predictions of both classes, and are reported as "insufficient
  dev data" otherwise.
- **Downstream effect:** compares the precision of surfaced evidence
  unweighted against weighted by pipeline confidence. A positive difference
  means confidence helps the learner model trust correct evidence more; a
  bootstrap interval is reported.
- **Abstention:** reported as `ambiguous_abstention_rate`, alongside the
  production policy (`confidence < 0.5`, or a non-error class, means nothing
  is surfaced).

### Calibration maps used by the app

`_select_errors` (the grammar agent) applies a per-model calibration map when
one exists for the model that answered, and then applies its 0.5 threshold to
the **calibrated** probability; the calibrated value also becomes the error's
`confidence` (the model's own is kept as `raw_confidence`). Without a usable
map it keeps the raw-confidence threshold and logs, once per model, that the
result is uncalibrated.

- **Fitting.** `python -m evals.real calibrate <dev_run_id>` (or
  `make eval-real-calibrate RUN=<dev_run_id>`) fits one map per model from a
  **dev-split** run and writes `evals/real/calibration/<provider_model>.json`.
  A run on any other split is refused, and a test checks that every committed
  map names a dev run whose manifest, split and dataset checksum match.
- **Method.** Platt scaling or histogram binning
  (`src/evaluation/statistics.py`), chosen by leave-one-out Brier score on the
  dev pairs alone. With fewer than 15 dev predictions, or one class only, the
  file records `status: insufficient_dev_data` and nothing is applied.
- **Format.** `calibration_version` `grammar-calibration-1.0`, the model key,
  the method and parameters, the dev sample size and the source run, split
  and dataset checksum. A file that is unreadable, of another version, for
  another model, not from dev, or with invalid parameters is logged and
  ignored.
- **Keys are exact.** A map for `ollama:llama3.1:latest` does not apply to
  `ollama:llama3.1:8b`, even when the two tags are the same weights.
- **Report.** For a test run, each model's section states the committed map's
  effect, computed offline from the recorded responses: ECE and
  false-correction rate (with precision and recall) before and after.

### Cross-provider, prompt variants and consistency

- **Cross-provider:** for the production prompt, each provider pair gets case
  agreement, Cohen's κ and an exact McNemar test on case correctness. The
  report also lists disagreements by category and the cases every provider got
  wrong.
- **Prompt variants:** `grammar_context@1` is an experimental prompt that adds
  the situation. It runs only on cases that have a context and is compared,
  paired, with `grammar@1`.
- **Consistency:** with `repeats > 1`, run-to-run agreement is reported.

## Statistics and quality gates

- Proportions get Wilson intervals. F1, ECE and paired differences get a
  seeded percentile bootstrap (seed and sample count are in the config).
- **Quality gates** (`EvalConfig.gates`) are judged on the interval. A gate
  passes only when the whole 95% interval is on the good side, fails only when
  the whole interval is on the bad side, and is `inconclusive` otherwise. With
  65 test cases, many intervals are wide enough to be inconclusive, and that
  is the honest outcome.
- **Production gate:** while the datasets are not expert-validated, the report
  says `production_gate: not_established`. A model must not be approved for
  production learner assessment on this benchmark alone.
- **Regression:** `python -m evals.real compare <base> <candidate>` pairs the
  two runs case by case for each provider and prompt name, and applies the
  exact McNemar test.
  - `regression` or `improvement`: p < α (0.05).
  - `no_significant_change`: otherwise. A lower point estimate alone is never
    called a regression.
  - `incomparable`: the runs use different dataset versions or splits, or one
    is synthetic and the other real.

## Reproducibility

`manifest.json` records:

- the config and its hash. Execution-only settings (timeouts, retries,
  concurrency) are excluded from the hash, and resuming a run under a
  different hash is refused;
- the dataset versions and file checksums;
- each prompt's template file and SHA-256;
- the git commit and whether the tree was dirty;
- Python and SDK versions;
- each provider's probe outcome, its model, and where the model came from:
  `model_source` is `app_default` or `override`, next to the
  `app_default_model`.

### Which model is evaluated

A provider named without a model (`claude`, `gemini`, `openai`, `ollama`)
is evaluated with the model the app runs by default: the code default in
`src/config.py` (`default_model_ids()`; `LLM_PRIMARY`, `LLM_FAST`,
`LLM_OPENAI`, `LLM_LOCAL`). The environment and `.env` are deliberately
ignored here, so a stale local setting cannot change what an evaluation
measures. To evaluate another model, name it: `claude:<model-id>`; the
manifest then records `model_source: override`.

`responses.jsonl` holds the full message list of every call.
`python -m evals.real report <run_id>` re-derives every number from these
files; the report finds a sibling `-dev` run automatically and uses it for
calibration fitting. `evals/real/history.jsonl` gets one line per run and
provider, with the headline metrics and the identity needed to compare them.

Run status is one of:

- `complete` — every planned call of every requested provider succeeded;
- `partial` — some calls or providers are missing or failed;
- `failed` — no call succeeded;
- `running`.

The report shows each provider's state: `complete`, `partial`, `failed`, or
`unavailable (<probe status>)`.

```bash
python -m evals.real validate
python -m evals.real probe ollama claude openai gemini
python -m evals.real run --providers ollama --config context-variant \
    --run-id my-test-run --timeout 900
python -m evals.real report my-test-run
python -m evals.real compare <base_run> <candidate_run>
```

## Results: first local run (2026-11-06)

These are real-model results, but treat them as **provisional**:

- every label is `author_labeled` (written by the AI assistant), not
  expert-validated;
- the test split is small (65 grammar cases, 11 vocabulary cases);
- only three small local models could be run.

The production gate is therefore `not_established`. No number below approves
a model for learner assessment.

Artifacts, with raw responses and the full prompts:

- `evals/real/runs/20261106-local-test/` — `report.md`, `report.json`,
  `responses.jsonl`, `manifest.json`;
- `evals/real/runs/20261106-local-dev/` — the dev split, used only to fit
  calibration maps.

### What was run

| provider / model | probe | test split | dev split |
|---|---|---|---|
| `ollama:llama3.1:latest` (8B, Q4_K_M) | available | complete, 81/81 calls | complete, 39/39 |
| `ollama:gemma2:2b` | available | complete, 81/81 | complete, 39/39 |
| `ollama:granite3.2:2b` | available | complete, 81/81 | not run |
| `claude` (`claude-sonnet-4-20250514`) | `auth_failed` | not run | not run |
| `openai` (`gpt-4o-mini`) | `auth_failed` | not run | not run |
| `gemini` (`gemini-2.0-flash`) | `auth_failed` | not run | not run |

- The hosted providers were **not evaluated**: the configured keys are
  invalid. The model ids in this table came from the local `.env` at the
  time and are not the app defaults: Claude was `claude-sonnet-4-20250514`
  (default `claude-sonnet-5-5`) and Gemini `gemini-2.0-flash` (default
  `gemini-3.6-flash`). Provider defaults now come from `src/config.py`
  (see *Which model is evaluated*). No hosted-model number exists anywhere in this repository.
- `granite3.2:8b` crashed Ollama with a CUDA error and was left out.
- Each test run made 81 calls: 65 grammar cases with `grammar@1`, 5 with
  `grammar_context@1` (the cases that have a situation), and 11 vocabulary
  cases.
- Every call used temperature 0 and one repeat, so run-to-run consistency was
  not measured.
- Hardware: CPU-mostly inference (2 GB GPU). The median call took 52–64 s
  and the slowest 186 s. Local inference has no cost.

### Grammar detection (test split, `grammar@1`, 63 labeled cases)

95% Wilson intervals; n is the denominator.

| metric | llama3.1 8B | gemma2 2B | granite3.2 2B |
|---|---|---|---|
| recall (n=35) | 0.14 [0.06, 0.29] | 0.91 [0.78, 0.97] | 0.46 [0.30, 0.62] |
| false-correction rate (n=28) | 0.11 [0.04, 0.27] | 0.68 [0.49, 0.82] | 0.32 [0.18, 0.51] |
| precision | 0.63 [0.31, 0.86] (n=8) | 0.63 [0.49, 0.75] (n=51) | 0.64 [0.45, 0.80] (n=25) |
| accuracy (n=63) | 0.48 [0.36, 0.60] | 0.65 [0.53, 0.76] | 0.56 [0.43, 0.67] |
| correction accuracy | 0.00 [0.00, 0.43] (n=5) | 0.65 [0.46, 0.81] (n=26) | 0.63 [0.39, 0.82] (n=16) |
| construction accuracy | 0.60 [0.23, 0.88] (n=5) | 0.12 [0.04, 0.29] (n=26) | 0.06 [0.01, 0.28] (n=16) |
| register acceptance (n=8) | 0.88 [0.53, 0.98] | 0.13 [0.02, 0.47] | 0.75 [0.41, 0.93] |
| dialect acceptance (n=4) | 1.00 [0.51, 1.00] | 0.25 [0.05, 0.70] | 0.25 [0.05, 0.70] |

**No model is usable as the app runs it today.** Every model fails at least
one quality gate (false-correction rate ≤ 0.10, recall ≥ 0.60,
schema-valid rate ≥ 0.95), and none passes all three.

- gemma2 finds errors but flags about two thirds of correct texts.
- granite3.2 misses about half of the errors.
- llama3.1 looks conservative, but that is a parser artefact (see the next
  section).

Segment results (by language, CEFR level, difficulty and category) are in the
report. With 2–35 cases per segment, almost every interval overlaps. Correct
but marked text (the `informal`, `formal` and `regional` categories) is where
false corrections concentrate: gemma2 accepts 1 in 8 register-marked texts
and granite3.2 1 in 4 regional ones. Three cases were missed by every model:
`es-003`, `fr-008` and `it-008`.

### Structured output

| metric (test, n=65) | llama3.1 | gemma2 | granite3.2 |
|---|---|---|---|
| JSON valid | 0.95 | 1.00 | 0.94 |
| schema valid (production parser) | **0.12** [0.06, 0.22] | 0.98 [0.92, 1.00] | 0.85 [0.74, 0.91] |
| bare top-level list | 0.83 | 0.00 | 0.09 |
| entries missing a required field | 0.00 (n=78) | 0.25 (n=77) | 0.07 (n=88) |

- **llama3.1 answers with a bare list** (`[...]`), not `{"errors": [...]}`, in
  83% of cases. The production parser reads that as "no errors".
- The report re-scores those answers as if wrapped. This is a diagnostic only;
  it is not what the app does, and no gate uses it. Re-scored, llama3.1's
  recall is 0.83 [0.67, 0.92] and its false-correction rate is
  0.75 [0.57, 0.87]. The model over-flags just like gemma2; the parser was
  hiding it.
- gemma2 leaves out `classification`, `severity` and `confidence` in a quarter
  of its entries. The production schema silently fills them with defaults
  (`classification` "wrong", `confidence` 1.0).
- **Defect found and fixed:** a model answered the vocabulary prompt with a
  bare list, and `_parse_vocabulary_response` raised `AttributeError`, which
  would end the user's turn. Off-contract JSON now yields no words.
  Regression test: `tests/test_agents/test_vocabulary_parser.py`.

### Evidence extraction and skill attribution

- The production pipeline attributes **every** surfaced error to the
  `grammar` skill. For all three models, skill accuracy is 1.00 on localized
  grammar errors and 0.00 on every localized `vocabulary` or `pragmatics`
  error (1–4 such errors per model).
- So the learner model never receives vocabulary-misuse or register evidence
  from the grammar agent, whatever the LLM says. This is a design gap, not a
  model failure.
- The construction ids the models emit rarely match the expected ids
  (`subskill_classification_accuracy` 0.06–0.12 for the 2B models). Most
  evidence therefore lands on construction ids the LKM does not recognize.
- No duplicate evidence events were produced.

### Calibration

- **granite3.2 and llama3.1 are over-confident.** Mean stated confidence is
  0.87 and 0.96, against detection accuracy of 0.47 and 0.50. The ECE is
  0.40 [0.25, 0.56] (n=34) and 0.46 [0.18, 0.75] (n=10).
- **gemma2's raw confidence** looks calibrated (ECE 0.05, n=45), but it uses
  only three distinct values and is missing on 27% of predictions.
- **gemma2's pipeline confidence**, after the production default of 1.0 is
  filled in, has ECE 0.29 [0.20, 0.46] (n=62).
- **Platt and histogram maps** were fitted on the gemma2 dev run (38
  predictions) and applied to test. They cut the pipeline ECE to 0.07
  (Platt) and 0.03 (histogram), with Brier scores 0.20 and 0.23. That is one
  model, one small dev set: an indication, not a validated calibrator.
- **No calibration maps were fitted for llama3.1 or granite3.2.** llama3.1's
  dev run surfaced only 9 predictions (15 are required), and granite3.2 has
  no dev run.
- **Committed maps (2026-11-08).** gemma2's map is Platt (selected over
  histogram by leave-one-out Brier on dev: 0.207 against 0.212). Its slope is
  negative (a = −0.127): on dev, higher stated confidence went with *lower*
  correctness. Applied offline to the test run, it lowers ECE from 0.29 to
  0.07 and the false-correction rate from 0.68 [0.49, 0.82] to 0.46
  [0.30, 0.64] (n=28 error-free cases), with precision unchanged (0.63) and
  recall down from 0.91 to 0.63. The intervals overlap; it is one small dev
  set and one model. llama3.1's map file records `insufficient_dev_data`
  (9 predictions), so the app keeps the raw threshold for it, as for every
  hosted model, none of which has been evaluated.
- **Confidence-weighting the evidence did not help.** For gemma2 it lowered
  the precision of the evidence fed to the learner model, by 0.047
  [0.009, 0.081]. For the other two models the change was not significant.

### Cross-provider and prompt-variant comparisons

- **The models do not agree with each other.** On the 65 test cases,
  pairwise agreement is 0.32–0.57, with Cohen's κ from −0.23 to 0.23.
- **No pair differs significantly in accuracy.** Exact McNemar p-values are
  0.13–0.49.
- **Supplying the situation (`grammar_context@1`) shows no measurable
  effect.** Only 5 test cases (3 on dev) have a situation. Paired accuracy
  was unchanged for gemma2 and granite3.2, and fell from 0.60 to 0.20 for
  llama3.1 (p = 0.5).
- The dataset needs many more context cases before this question can be
  answered.

### Vocabulary extraction (test, 11 cases)

| metric | llama3.1 | gemma2 | granite3.2 |
|---|---|---|---|
| schema valid | 1.00 [0.74, 1.00] | 0.91 [0.62, 0.98] | 0.36 [0.15, 0.65] |
| precision | 0.92 (n=25) | 0.80 (n=39) | 1.00 (n=9) |
| recall (n=29) | 0.59 [0.41, 0.74] | 0.66 [0.47, 0.80] | 0.17 [0.08, 0.35] |
| forbidden-word rate | 0.08 | 0.10 | 0.00 |

Translations of correctly extracted words were all accepted. Eleven cases
are too few for any conclusion beyond "llama3.1 and gemma2 roughly work, and
granite3.2 mostly fails the output format".

### What these results support

1. **The production grammar parser should accept a bare top-level list**, or
   the prompt should be enforced with a JSON schema. As shipped, this hides
   most of llama3.1's output.
2. **Missing `classification` and `confidence` should not default to
   "wrong" and 1.0.** The defaults turn incomplete answers into confident
   error evidence.
3. **The grammar pipeline needs skill attribution** for vocabulary and
   pragmatics findings.
4. **None of the small local models tested is fit to feed the learner
   model.** Hosted models still need to be evaluated with valid keys.
5. **The next data work:** expert annotation of the test split, and more
   context and register cases.

Items 1–3 change production behaviour, so they are left as proposals and not
made here.
