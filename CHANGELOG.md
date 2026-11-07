# Changelog

All notable changes to Polyglot Swarm are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Reply before analysis (ADR-0036).** `POST /api/v1/chat` returns as soon
  as the conversation node replies. The turn's grammar, vocabulary and
  cultural analysis, the evaluator and the adaptive step run as a
  per-session background task that the next turn and the session end wait
  for, so evidence, vocabulary and the report are unchanged. A pending
  analysis is marked in the session snapshot and re-run after a restart; an
  analysis failure is logged and skipped.
  - **API contract:** `hidden_feedback` covers the turns analyzed before
    this one and adds `through_turn`. Turn N's feedback arrives with the
    response to turn N+1 and in the end-of-session report.
  - SQLite work on the chat and session paths (including finalization's
    persistence) runs in worker threads.
  - The CLI runs its session in one event loop, so analysis overlaps the
    learner typing, and finalizes through the session registry, which marks
    its snapshot finalized (it was left `active` before, so idle recovery
    could finalize a CLI session a second time). The Gradio UI waits for
    the analysis before returning, as before.
  - `ops/loadtest.py` takes `--think-ms`, a pause between chat turns.
  - Measured (600 ms per model call, one learner): chat p95 731 ms with a
    3 s pause between turns, 1,391 ms with none (1,428 ms before), since the
    next turn waits for the previous analysis. No gain from about 10
    concurrent learners. See `docs/production/performance-report.md`.
  - The `run_turn` docstring said the turn stopped once the conversation
    node replied; it waited for the evaluator. It now does what it says.
- **One planner.** `/learner/plan` (what the UI shows), `/learner/insights`
  and `polyglot plan` now use the adaptive next-best-activity engine
  (`adaptive-nba-v1`, ADR-0033), the one that was evaluated, through the new
  `src/adaptive/service.py`. `/learner/recommendations` serves the same plan
  with its full rationale.
  - `PlanResponse` keeps its shape. `type` is now the engine's activity
    (`grammar_practice`, `vocabulary_review`, `diagnostic_check`, ...),
    `reason` its first rationale line, `priority` its score, and `intent`
    one of `assessment`, `remediation`, `reinforcement`, `progression`,
    `introduction`, `review` (`advancement` is gone). The frontend labels
    the new intents.
  - `/learner/plan` records each served plan in the adaptive audit trail
    (`record=false` to preview), as `/recommendations` does; the engine reads
    the last recorded plan to keep task difficulty continuous.
  - The curriculum planner (`src/curriculum/`: `plan_next_actions`,
    `plan_next_best`, its actions, objectives and difficulty helpers) was
    removed. `PlanConstraints` moved to `src/adaptive/constraints.py`.
  - The curriculum eval suite drives the adaptive engine and seeds grammar
    errors as evidence, as conversation finalization records them. Its
    difficulty-appropriateness eval was removed with the old helper.
    `target_coverage` is gated at a 60-minute plan and also reports
    `coverage_at_15_min` (0.714): at the UI's default 15 minutes, a new
    learner's B1/B2 grammar weakness can rank below assessments and an
    introduction.
  - The adaptive simulation's `existing_planner` policy was removed with the
    planner; paired differences are now against `static`.
- **One backup module.** `src/security/backup.py` was removed;
  `src/ops/backup.py` (verified backup sets) is the only implementation.
  `polyglot security backup|backups` are now aliases of
  `polyglot ops backup|backups`. Plain `*.backup.db` files written by the
  old command are no longer listed; they are left in place.

### Added

- **Calibrated correction confidence.** The grammar agent's `_select_errors`
  applies a per-model calibration map for the model that answered
  (`governance.last_answer()`), and its 0.5 threshold then applies to the
  calibrated probability, which becomes the error's `confidence`
  (`raw_confidence` keeps the model's own). Without a usable map (absent,
  `insufficient_dev_data`, or corrupt) it keeps the raw threshold and logs
  the model once as uncalibrated.
  - `src/evaluation/calibration_maps.py` fits (Platt or histogram, chosen by
    leave-one-out Brier on dev) and loads versioned map files.
  - `python -m evals.real calibrate <dev_run_id>` /
    `make eval-real-calibrate` writes them to `evals/real/calibration/` and
    refuses any non-dev run.
  - Committed: `ollama:gemma2:2b` (Platt, 38 dev predictions) and
    `ollama:llama3.1:latest` (`insufficient_dev_data`: 9 dev predictions, so
    it stays uncalibrated).
  - The report of `20261106-local-test` was rescored offline and now states
    the committed map's effect: for gemma2, ECE 0.29 → 0.07 and
    false-correction rate 0.68 → 0.46, with recall 0.91 → 0.63.

- **Production maturity baseline (ADR-0035).** The audit and risk register
  are in `docs/production/`.
  - **Durable chat sessions:** a snapshot after every turn, rehydration after
    a restart, recovery that finalizes idle and abandoned sessions,
    finalize-exactly-once claims, and a per-user active-session cap.
  - **LLM governance:**
    - per-attempt timeouts;
    - per-user and deployment-wide daily budgets, plus call quotas;
    - a per-turn call cap (runaway-loop guard), with `429 budget_exceeded`;
    - the answering model, marked as a fallback where it was one, recorded
      on session evidence.
  - **`Idempotency-Key` support** on chat, review submission and the
    assessment endpoints.
  - **Environment profiles:** `APP_ENV=staging|production` fails fast on
    unsafe configuration; `polyglot ops config-check` reports the problems.
  - **Edge protections:**
    - request ids and a structured access log;
    - a request-body size limit and security headers;
    - a per-user work rate limit;
    - a JSON 500 handler that carries the request id;
    - a minimum password length;
    - readiness that checks the schema version.
  - **Observability:** `/metrics` (Prometheus format, behind a token),
    Prometheus alert rules and a Grafana dashboard under `ops/`, and an
    operations runbook.
  - **Backups as verified sets** (database, media and profiles, with a
    checksum manifest):
    - restore, retention, and automatic pre-migration backups;
    - a nightly backup service in `docker-compose.prod.yml`;
    - `polyglot ops backup | backups | verify | restore | maintenance |
      db-check | config-check`.
  - **Deployment:**
    - `docker-compose.prod.yml` (API only, published on loopback, read-only
      root filesystem);
    - `.env.production.example`;
    - a non-root image built against `requirements.lock`.
  - **Supply chain in CI:**
    - a secret scan, the ruff security rules, and a pip-audit gate with
      version-pinned, dated acceptances;
    - `npm ci` with an audit and a production build;
    - a container job that rehearses a staging deploy, backup and restore.
  - A load-test harness (`ops/loadtest.py`) and the performance report.

- **Multimodal (speech) assessment (ADR-0034).**
  - **Pipeline** (`src/multimodal/`), with separate stages: ingestion
    (format sniffing, size and duration limits, ffmpeg decoding, signal
    quality), speech-to-text behind a provider protocol (local Whisper with
    word timing, word probabilities, language identification and retries),
    speaking assessment, listening assessment, evidence mapping, and
    storage.
  - **Speaking dimensions,** each with an explicit basis and abstention:
    - `fluency` from timing measures only (rate, pauses, run length,
      repetitions), scored with a map fitted on expert ratings for English
      read-aloud only, and measures-only exposure elsewhere;
    - `intelligibility`: read-aloud target words the recogniser understood.
      This is not phonetic accuracy. Because the recogniser was shown to
      miss accented-but-correct words, there are no word-level corrections;
    - a `pronunciation` acoustic proxy that abstains unless validated
      against expert ratings for the language;
    - `spoken_grammar` via the existing grammar agent, for confident
      free-speech transcripts only.
  - **Listening:** recognition, comprehension and recall questions, answered
    by choosing or typing, so scores are independent of speech recognition
    and of speaking. Includes an 8-task Spanish bank (A1–B2, five regional
    voices, three speech rates; author-written, not expert-validated).
  - **API:** `/api/v1/assessment/speaking`, the listening tasks, audio and
    answers endpoints, and `/api/v1/assessment/submissions` (list, get,
    delete).
  - **Frontend:** a listening exercise on the home page, and
    `useVoice.stopAndAssess`.
  - **Evidence:**
    - Schema v3 and migration 0009 add `modality`, `media_ref`, `processing`
      and `transcription_confidence` (kept separate from the evaluator's
      `confidence`) to evidence, plus a `media_submissions` table.
    - The learner model discounts transcript-derived evidence by the
      recogniser's confidence, and accepts continuous `scored` outcomes.
  - **Privacy:** raw audio is not kept unless the learner consents, and is
    then purged after 30 days. Submissions are covered by privacy export and
    deletion. Neither audio nor transcripts are logged.
  - **Benchmark:** `python -m evals.speech` runs the real recogniser on three
    data types, kept separate: speechocean762 (external, expert-labelled,
    English), synthetic Spanish (Edge TTS), and offline format and edge-case
    checks. Results are in `docs/multimodal-assessment.md`; the benchmark
    led to the fluency scope, the pronunciation proxy staying off, and a
    gate for Whisper repetition loops.

- **Adaptive learning intelligence (ADR-0033).**
  - **Subskill learner model `lkm-subskill-v1`** (`src/adaptive/learner_model.py`)
    on top of `lkm-evidence-v2`. It adds:
    - construction-level estimates, with intervals;
    - a performance pattern that separates a one-session dip from a
      persistent decline or weakness;
    - leakage-guarded success predictions;
    - the posterior probability that an objective is mastered.
  - **Adaptive difficulty:** targets ~75% predicted success. Steps are
    bounded, a one-session dip holds the difficulty, and task difficulty is
    kept apart from the content's CEFR level.
  - **Next-best-activity engine `adaptive-nba-v1`:** deterministic and
    LLM-free. It chooses among remediation, assessment, reviews,
    reinforcement, progression, introduction, vocabulary expansion and
    conversation. Each recommendation carries:
    - a transparent component score;
    - its rationale and expected benefit;
    - its evidence ids;
    - its uncertainty;
    - its difficulty decision.
  - **Personalized learning paths:** per-objective states, prerequisite
    gaps, short- and long-term horizons, skill balance, recurrent errors, and
    explained changes since the previous path.
  - **Retention view:** FSRS memory states replayed from demonstrated recall,
    for words and constructions. Exposure is never counted as recall,
    recognition is weaker than production, and leeches are detected.
  - **API:** new endpoints `GET /api/v1/learner/recommendations`, `/path`,
    `/predictions` and `/decisions`. Migration 0008 adds the
    `adaptive_decisions` audit table, which is included in privacy export
    and deletion.
  - **Evaluation:** `python -m evals.adaptive` (SIMULATED learners only)
    runs two comparisons:
    - learner models (legacy, v2, BKT, Elo, v1) on held-out learners;
    - five planning policies, from a static syllabus to the full adaptive
      engine, on immediate and delayed outcomes.

    Results are in `docs/adaptive-learning.md`; none are real learner
    outcomes.

- **Real-model evaluation framework (ADR-0032).** A new package,
  `evals/real/` (`python -m evals.real`), measures whether real LLMs assess
  learner language correctly. It is separate from the offline
  `python -m evals`.
  - **Datasets:** versioned and checksummed, with group-hashed `dev`/`test`
    splits, leakage checks, per-case annotation provenance, a labeling rubric,
    and acceptable alternatives. `grammar-2026.11.0` has 98 cases in 5
    languages and 10 categories (correct, incorrect, vocabulary misuse,
    context-inappropriate register, acceptable alternative, regional, formal,
    informal, ambiguous, adversarial). `vocabulary-2026.11.0` has 14 cases.
    All cases are labelled `author_labeled` (written by the AI assistant),
    not expert-validated, and reports say so.
  - **Runner:**
    - Builds each concrete provider directly, with no failover and no
      synthetic substitution; the fake provider runs only with
      `--allow-synthetic` and is labelled throughout.
    - Probes availability (auth failure, unreachable, model missing, ...).
    - Sends production-identical prompts and parameters, with timeouts,
      retries and resume.
    - Preserves every raw response together with its prompt, parameters,
      reported model, token usage, latency and estimated cost.
  - **Scoring:** replays the production parser, error policy and evidence
    pipeline, and measures:
    - grammar precision, recall, F1, false-correction and missed-error rates,
      localization, correction and construction accuracy;
    - acceptable-alternative, synonym, dialect and register handling, context
      sensitivity, vocabulary misuse, ambiguity abstention, and adversarial
      robustness;
    - structured-output validity and missing/invalid fields;
    - evidence extraction (skill, subskill and difficulty classification,
      duplicates);
    - vocabulary extraction;
    - calibration: raw versus pipeline confidence, ECE, Brier, reliability,
      risk–coverage, and Platt/histogram maps fitted on dev only;
    - downstream evidence weighting;
    - cross-provider agreement, κ and McNemar, plus systematic disagreements.
  - **Statistics:** new `src/evaluation/statistics.py` provides Wilson,
    bootstrap, exact McNemar, κ, Brier, AURC, Platt and histogram calibration,
    and gate decisions based on confidence intervals.
  - **Reports:** `report.json` + `report.md` per run, marking runs and
    providers complete, partial, failed or unavailable.
    `history.jsonl` tracks results over time. `compare` detects regressions
    with a paired test and refuses incomparable runs.
  - **Prompts:** an experimental `grammar_context@1` prompt (the situation
    added to the grammar prompt), measured against production `grammar@1`.
  - **Providers:** `LLMProvider.generate_detailed()` returns reported token
    usage and model identity. The grammar and vocabulary agents' message
    construction is extracted into `build_grammar_messages` /
    `build_vocabulary_messages`; agent behaviour is unchanged.
  - **CI:** validates the datasets and type-checks `evals/real` offline, and
    an opt-in `real_model` pytest marker covers the provider tests. New
    scheduled or manual workflow `real-model-eval.yml`, and new Makefile
    targets `eval-real-validate`, `eval-real` and `eval-real-report`.
  - **First real results (provisional).** Three local Ollama models
    (llama3.1 8B, gemma2 2B, granite3.2 2B) were run on both splits; the
    hosted providers were recorded as `auth_failed` and not evaluated. Results
    are in `docs/real-model-evaluation.md`, with raw responses under
    `evals/real/runs/`. No tested model passes the provisional gates.
    Reports also re-score bare-list grammar answers as a diagnostic: the
    production parser reads them as "no errors", which hid most of llama3.1's
    output.

- **10/10 gap closure.** Closed the three gaps a full audit against the plan's
  Definition of Done found still open after Phases 0-24 — Gate C (learning
  evidence), a Gate B over-claim (versioned prompts), and Gate E product gaps:
  - **Gate C — experiment execution harness.** `src/experiments/runner.py`'s
    `run_ablation_study` joins the ablation graph builder
    (`build_ablation_graph`, arms A-E) to the outcomes store: it runs a
    scripted cohort through each arm's graph, measures mean learner-model
    mastery before and after, and records the outcomes — a runnable
    controlled comparison, where before there was only a graph builder and an
    outcomes table with nothing connecting them. `src/memory/experiments.py`
    gains `assign_to_variant` and `due_measurements`, the missing
    delayed-retention *producer* that turns the `delayed_1d/7d/30d`
    measurement points into a concrete due-work list from each assignment's
    timestamp. Exposed via `polyglot experiment ablation` / `polyglot
    experiment due`.
  - **Gate C — published results.** `src/experiments/results.py` +
    `polyglot results` (and `make results`) run the benchmark, evaluation,
    and ablation harnesses deterministically and write `docs/results.md` with
    the *actual measured numbers* plus a Known Limitations section — the
    plan's previously-unchecked "published results" / "known limitations"
    boxes. The generator refuses to run outside deterministic mode so the
    artifact is always reproducible.
  - **Gate B — versioned prompts.** `src/llm/prompts/registry.py` is a real
    prompt registry: every agent prompt has a logical name, a current
    version, and a template file (`PROMPT_REGISTRY`), and `render_prompt`
    returns a `RenderedPrompt` carrying its name/version. The four core
    prompts that were inline Python string constants (grammar, vocabulary,
    conversation, review) are migrated to versioned `*_v1.jinja2` templates,
    and every agent now renders through the one versioned path — replacing
    the previous mix of unversioned templates and inline strings.
  - **Gate E — voice, PWA, and onboarding in the web app.** New
    `POST /api/v1/voice/transcribe` and `POST /api/v1/voice/speak` endpoints
    (base64 audio JSON, auth-scoped, 503 when the `voice` extra is absent).
    The React app gains a mic button and spoken-reply playback
    (`useVoice`/`ChatPanel`), a real PWA/mobile setup (viewport export,
    populated manifest + icon, an app-shell service worker that never caches
    API traffic), and a first-run onboarding wizard (`Onboarding`) that
    captures the learner's language and goal. A CI `frontend` job now
    type-checks and vitest-tests the web app.

- **Phase 24 — Open-source quality.** Documentation and community
  infrastructure for external contributors:
  - `docs/architecture.md`, `learner-model.md`, `evaluation.md`,
    `language-packs.md`, `providers.md`, `privacy.md`, `deployment.md`,
    `contributing.md` — grounded in the actual implementation (function/class
    names, file paths, real data flow) rather than the earlier product
    research in `docs/DESIGN.md`, which remains the historical vision
    document but is not kept in sync with the code.
  - `.github/ISSUE_TEMPLATE/` (bug report, feature request, and a
    `config.yml` pointing blank issues to GitHub Discussions) and
    `.github/PULL_REQUEST_TEMPLATE.md`.
  - `SECURITY.md` (private vulnerability reporting process and scope),
    `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), and `RELEASING.md` (the
    release process: versioning via `src/__init__.py`, `CHANGELOG.md`
    discipline, and the cut-a-release checklist — none of which existed
    before, since the project has not yet cut a numbered release).
  - `README.md` and `CONTRIBUTING.md` cross-link the new `docs/` pages and
    community files.

- **Phase 23 — Production reliability.** Failure in one dependency should
  degrade the affected feature, not crash the turn or block unrelated
  writes:
  - `src/llm/reliability.py` (new) — `CircuitBreaker` (per-provider-name
    consecutive-failure tracking; opens for a cooldown window after repeated
    failures instead of retrying a known-dead provider on every subsequent
    turn) and `RetryPolicy`/`backoff_delay` (bounded exponential backoff).
    `RoutingProvider.generate` (`src/llm/factory.py`) now retries the same
    provider with backoff before failing over, and consults/updates the
    circuit breaker per attempt. New settings: `llm_max_retries`,
    `llm_retry_base_delay`, `llm_retry_max_delay`,
    `llm_circuit_breaker_failure_threshold`,
    `llm_circuit_breaker_cooldown_seconds`.
  - `src/agents/conversation.py` — if the entire provider chain is exhausted
    (every provider unavailable, circuit-broken, or failed after retries),
    the turn no longer crashes: it degrades to a canned, in-character,
    language-specific fallback reply (Spanish/Polish/Italian variants plus an
    English default) instead of propagating the exception.
  - `src/orchestrator/lifecycle.py`'s `persist_session` — `analytics
    .record_error`/`analytics.log_session` failures are now isolated
    (logged, not raised), so an analytics-store outage can no longer prevent
    `sessions.end_session(status="completed")` or the knowledge-model update
    that run afterward in the same function from happening.
  - `src/speech/livekit_agent.py`'s default synthesizer now falls back to
    empty (text-only) audio on `SpeechDependencyError` or any TTS failure,
    matching the fallback `frontend/gradio_app.py` already had — a voice turn
    is no longer lost entirely just because audio couldn't be produced.
  - `src/api/app.py` — new `GET /ready` readiness endpoint, distinct from the
    liveness-only `GET /health`: checks the database (`SELECT 1`), the LLM
    provider chain (config-only, no network calls), and the vector store
    (degrades rather than fails overall readiness, since it's an enrichment
    layer). Returns 503 if the database or every LLM tier is unavailable.
  - `src/observability/logging_config.py` (new) — centralized logging
    configuration (`configure_logging`/`ensure_configured`), with a
    `JsonFormatter` for structured, log-aggregator-friendly output alongside
    the human-readable text format. Controlled by new `log_level`/
    `log_format` settings; wired in at both the CLI and API-server entry
    points, since neither previously called `logging.basicConfig` at all.

- **Phase 22 — Cost and latency optimization.** Makes the per-turn/per-session
  cost of running the system visible and reduces it where quality doesn't
  need the extra spend:
  - `src/llm/cost.py` (new) — `CostSummary` (calls/tokens/cost_usd/
    mean_latency_ms/failures/by_tier) plus `session_cost`/`user_cost`/
    `turn_cost`, all reusing the existing `model_runs` table and the Phase 17
    observability link table rather than adding new storage. Exposed via
    `polyglot cost session/user` and `GET /api/v1/cost/session/{id}` /
    `GET /api/v1/cost/me` (auth-scoped to the caller).
  - `src/agents/evaluator.py` — budget-aware routing: the evaluator now
    escalates from the cheap "fast" tier to the costlier "primary" tier only
    when at least one grammar error in the turn is judged high-impact
    (`src.evaluation.policies.is_high_impact`); previously every evaluation
    call used "fast" unconditionally.
  - `src/agents/conversation.py` — conversation history sent to the LLM is
    now capped to the most recent `MAX_HISTORY_MESSAGES` (20) turns
    (`_windowed_history`) instead of the full transcript since session
    start, which previously grew cost and latency unboundedly with session
    length.
  - `src/scenarios/loader.py` — scenario YAML files (static content) are now
    cached in memory, keyed by `(path, mtime)` so an on-disk edit still
    invalidates the cache automatically; previously every scenario load
    re-parsed the file from disk.

- **Phase 21 — Security and privacy.** Made privacy a real, enforced feature
  rather than a policy statement:
  - `src/api/auth.py` hardening: bearer tokens are hashed (SHA-256) before
    storage rather than kept raw, and now expire (`settings.token_ttl_hours`,
    default 30 days) — `resolve_token` treats an expired token exactly like an
    unknown one. Added `purge_expired_tokens`, `delete_tokens_for_user`, and
    `delete_user` for account cleanup.
  - `src/security/` — `rate_limit.py` (an in-process fixed-window
    `RateLimiter`, wired into `/auth/login` and `/auth/register` with a 429
    response), `secrets.py` (Fernet-based `encrypt_secret`/`decrypt_secret`
    for secrets-at-rest, reusing the already-vendored `cryptography` package —
    no new dependency), `backup.py` (`create_backup`/`list_backups` using
    SQLite's online backup API), and `audit.py` (an append-only `audit_log`
    table; `anonymize_for_user` nulls the `user_id` on erasure rather than
    deleting the security record).
  - `src/memory/privacy.py` — `export_user_data`/`delete_user_data` aggregate
    every user-keyed store (profile, vocabulary, collocations, conversation
    turns, error patterns, learning sessions, skill beliefs, assessments,
    evidence, experiment participation, model runs via the observability
    link table, ChromaDB cultural notes, and the account/tokens themselves)
    into one self-service export or a complete, per-store-reported deletion.
    Exposed via `GET /api/v1/privacy/export` / `DELETE /api/v1/privacy/data`
    (self-service, auth-scoped to the caller only) and `polyglot privacy
    export/delete`.
  - `settings.telemetry_enabled` gates whether LLM-call telemetry is
    persisted to `model_runs` at startup; `settings.local_only` makes the
    provider factory exclude every hosted provider (Claude/Gemini/OpenAI)
    regardless of configured API keys, leaving only Ollama/local — an
    enforced "no learning data leaves this machine" guarantee, not a
    suggestion.
  - `polyglot security backup/backups/audit` CLI commands.

- **Phase 20 — Safety and correctness.** Hardened the system against
  prompt injection and unverified claims, per the plan's rule that "external
  text must always be treated as untrusted data" and "retrieved content must
  never become system instructions":
  - `src/safety/` — `injection.py` (`scan_for_injection` heuristic detection,
    `wrap_untrusted`/`UNTRUSTED_DATA_NOTICE` — the same delimiter pattern
    `src.agents.ingestion` already used for fetched external content) and
    `roleplay.py` (`disclaimer_for_role` for sensitive personas,
    `validate_scenario_content` rejecting scenario definitions whose
    free-text fields look like an injection attempt).
  - `src/agents/conversation.py`'s system prompt now renders scenario-derived
    persona/location/objectives inside an explicit `<SCENARIO>...</SCENARIO>`
    block with the untrusted-data notice, and appends a disclaimer for
    medical/legal personas (practice role-play only, never real advice).
  - `src/scenarios/loader.py` validates scenario content (not just structure)
    at load time, rejecting a malicious scenario file before it ever reaches
    an agent prompt.
  - Cultural notes now carry a `confidence` and are filtered through the same
    abstention threshold grammar corrections use
    (`src.evaluation.policies.ABSTAIN_THRESHOLD`) — a fabricated or
    low-confidence cultural claim is dropped before it reaches the learner or
    the vector store.

- **Phase 19 — Learning science experiment platform.** Turns the plan's
  controlled-comparison design into runnable infrastructure:
  - `src/memory/experiments.py` gains `record_outcome`/`get_outcomes`/
    `summarize_outcomes` (a new `outcomes` table) for measuring pre-test,
    intervention, immediate-post, and 1/7/30-day delayed outcomes per
    experiment variant — reusing the existing multidimensional CEFR profile
    as the measurement instrument rather than building a separate "test".
  - `src/orchestrator/graph.py`'s `build_graph` gains an optional
    `components` parameter (`{"analysis", "review"}`) and
    `build_ablation_graph`/`ABLATION_ARMS` implementing the plan's five-arm
    ablation ladder (A: conversation-only .. E: full system), so which
    architectural components actually create learning value can be measured
    directly. The default (`components=None`) is unchanged from before this
    parameter existed.
  - `polyglot experiment create/assign/measure/report` CLI commands.

- **Phase 18 — Evaluation harness.** A versioned `evals/` suite so "every
  model/prompt change runs evaluation" is a real, runnable command:
  - `evals/harness.py` — `EvalResult`, `run_evals`/`all_evals`/`format_results`
    (mirroring `benchmarks/harness.py`'s shape and failure-tolerance), plus
    `isolated_storage()` for suites that need throwaway SQLite storage.
  - Four capability suites with their own hand-labeled, versioned datasets:
    `evals/grammar` (precision/recall/F1/false-correction-rate + calibration,
    reusing `_select_errors`), `evals/vocabulary` (extraction precision/recall/
    F1 + a never-raises robustness check), `evals/assessment` (correlation with
    expert-equivalent CEFR bands, absolute error, calibration, confidence
    coverage), and `evals/curriculum` (target coverage, skill balance,
    difficulty appropriateness against the real planner).
  - `evals/regression` — a single pass/fail gate rolling up grammar,
    vocabulary, and assessment for a one-signal CI check.
  - `src/evaluation/metrics.py` — shared `precision`/`recall`/`f1_score`/
    `false_positive_rate`/`mean_absolute_error`/`pearson_correlation`, filling
    the gap `benchmarks/grammar_bench.py` had been computing inline.
  - `python -m evals` / `make eval`, and a CI step alongside the benchmark smoke
    check.

- **Phase 17 — Observability & tracing.** LLM calls and evidence are now
  correlated so a turn can be reconstructed end-to-end:
  - `src/observability/context.py` — a contextvar-based `interaction_scope()`
    binding an interaction id (and session id) for the duration of a turn,
    without threading the id through every function signature.
  - `RoutingProvider._record` stamps every `ModelRun` with the ambient
    interaction id; `LearningEvent.create` falls back to it too when no
    explicit provenance is given.
  - `src/observability/trace.py` — `assemble_trace` stitches a session's
    evidence events and model runs (joined via a new `session_interactions`
    link table, since `model_runs` carries no session column) into an ordered,
    auth-scoped `Trace`; `format_trace` renders it as ASCII-safe text.
  - `GET /api/v1/trace/{session_id}` and a `polyglot trace` CLI command.

- **Phase 16 — Production frontend for the learner model.** The learner model
  (plan, CEFR profile, skill map, insights) is now exposed end-to-end:
  - New `src/api/routes/learner_routes.py` (`/api/v1/learner/plan|cefr|
    skill-map|cefr-history|insights`) with typed response schemas.
  - React: `api.ts` client functions, a `usePlan` hook, and a `TodaysPlan`
    component rendering ranked actions with reasons, a CEFR skill map, and
    insights on the home page — answering "what should I practise today, and
    why?".

- **Phase 15 — Voice activity detection & pronunciation integration.**
  - `src/speech/vad.py` — a VAD stage (`has_speech`) with an optional
    `webrtcvad` backend and a dependency-free energy-based fallback, following
    the lazy-import + `SpeechDependencyError` pattern so it works offline.
  - `VoicePipeline` runs VAD before STT (skipping the expensive stages on
    silence) and can score pronunciation on a normal turn via `expected_text`,
    while preserving the `{transcript, reply, audio, pronunciation}` result
    shape and injectable stages.

- **Phase 14 — Adaptive difficulty controller.** Difficulty adaptation moved
  from a single "more correct → harder" rule to a multi-signal controller
  (`src/agents/difficulty_signals.py`): accuracy, lexical diversity, response
  length, repair frequency, and fatigue each vote toward easier/harder/steady.
  `adaptive_node` blends this with the evaluator's signal (a safety veto backs
  off on any "too hard") while keeping its `{cefr_level, current_scenario}`
  contract and attaching the signals for observability.

- **Phase 13 — Scenario engine as pedagogical environments.** Scenarios now
  declare `target_grammar`, `target_vocabulary`, `target_functions`,
  `constraints`, `failure_conditions`, and `transfer_opportunities` (all
  optional). The conversation agent uses them to *create opportunities* for the
  target skills (subtle in-character steering), and the session report surfaces
  a scenario success/failure outcome via `evaluate_success`.

- **Phase 12 — Multidimensional CEFR assessment.** CEFR is now a profile, not a
  single number (`src/assessment/`):
  - `cefr_profile.py` builds a per-skill CEFR band (speaking/listening/reading/
    writing/grammar/vocabulary/pragmatics) with a confidence and sample size
    from the learner knowledge model, persisted to the `assessments` store.
  - `assessment_node` additionally records the multidimensional profile while
    still returning `{cefr_level}` and updating the profile.
  - A `polyglot assess` CLI command shows the profile.

- **Phase 11 — Cross-language transfer graph.** Transfer suggestions are now
  grounded in a linguistic resource, not pure LLM invention:
  - `src/languages/transfer_graph.py` retrieves candidate relations (cognates,
    false friends, interference) from `languages/<code>/transfer/<target>.yaml`.
  - `suggest_transfers` retrieves candidates then uses the LLM to *verify* them,
    falling back to the resource-backed relations offline; the
    `transfer_suggestions` output shape is preserved.
  - Seed resources for Spanish↔Italian (cognates + false friends) and
    Spanish→Polish (interference).

- **Phase 10 — Language packs.** Formalized `languages/<code>/` into full packs:
  - A general pack loader (`src/languages/pack.py`) reading `metadata.yaml`,
    `frequency/`, `collocations/`, and `register/`, reusing the shared
    `paths.py` code/root resolution; the grammar taxonomy loader was refactored
    onto the same foundation.
  - Seed packs for Spanish, Polish, and Italian (three deliberately different
    languages) with metadata, frequency lists, collocations, and register notes.

- **Phase 9 — Evaluator / verifier.** The evaluator becomes a genuine safety
  layer (`src/evaluation/`):
  - `verifier.py` — per-correction accept / revise / reject / **abstain**;
    low-confidence corrections are suppressed rather than asserted (a false
    correction is worse than a missed one).
  - `policies.py` — high-impact detection and the confidence→decision mapping.
  - `conflict.py` — reconciles grammar-vs-cultural register conflicts.
  - `calibration.py` — Expected Calibration Error + reliability buckets, plus a
    deterministic calibration benchmark.
  - `evaluator_node` now routes corrections through the verifier while
    preserving its existing `{evaluation, grammar_errors}` contract (the legacy
    `overrides` index protocol still works).

- **Phase 8 — FSRS integration & contextual review.** Kept FSRS deterministic
  and made the WHAT/WHEN split explicit (curriculum decides what, FSRS decides
  when):
  - `src/agents/review.py` — `generate_contextual_review` embeds a due item in a
    scenario-style retrieval cue (falls back to a plain cue offline);
    `grade_review` runs FSRS, persists the outcome, updates the recognition
    dimension, emits a `REVIEW_RESULT` evidence event, and updates the learner
    model — so mastery reflects *demonstrated recall*, not scheduler assumptions.

- **Phase 7 — Next Best Learning Action.** A curriculum planner
  (`src/curriculum/`) that selects the highest-value next action:
  - `actions.py` (11 action types), `constraints.py` (time/fatigue/goal budget),
    `difficulty.py` (desirable-difficulty + uncertainty bonus), `objectives.py`
    (Expected Learning Value), and `planner.py` (`plan_next_actions` /
    `plan_next_best`) reading the learner model, due reviews, and weaknesses.
  - A `polyglot plan` CLI command showing today's plan with explanations.

- **Phase 6 — Learner Knowledge Model & mastery engine.** A new `src/learner/`
  package that models what the learner can and cannot do:
  - `mastery_engine.py` — a transparent weighted-evidence rule that turns a
    prior belief plus a batch of evidence into a posterior mastery and
    uncertainty per skill (acceptable variation is not treated as a gap).
  - `uncertainty.py` — uncertainty shrinks as (confidence-weighted) evidence
    accumulates; includes a Wilson-interval helper.
  - `skill_graph.py` — skill/construction prerequisite relations and readiness
    checks (construction prerequisites come from the language packs).
  - `knowledge_model.py` — reads/writes `skill_states`, updates beliefs from
    evidence, and snapshots the model (`learner_state_snapshots`).
  - `persist_session` now updates the learner model from each session's events
    and writes a snapshot.

- **Phase 5 — Vocabulary intelligence.** Vocabulary is no longer known/unknown:
  - A v3 migration adds per-word mastery dimensions (recognition, production,
    listening, spelling) plus register, frequency rank, first-seen/first-produced,
    and production counters — additive and idempotent (fresh and upgraded DBs).
  - `record_dimension`/`set_metadata`/`mastery_summary` update dimensions from
    observations; `persist_session` bumps the production dimension per produced
    word.
  - Collocations (e.g. "tomar una decisión") are first-class learning objects
    (`collocations` table + store).

- **Phase 4 — Grammar intelligence.** Grammar feedback moved from "everything is
  an error" to a structured taxonomy:
  - `GrammarErrorModel`/`GrammarError` gain a `classification`
    (wrong/awkward/unusual/regional/formal/informal/acceptable), `construction`,
    calibrated `confidence`, and `alternatives`; the legacy fields are preserved.
  - `grammar_node` uses `generate_structured` and only surfaces genuine,
    confident errors — regional/informal/acceptable variation is recognized and
    not "corrected" (it abstains below a confidence threshold).
  - Language packs (`languages/{es,pl,it}/grammar/`) seed a grammar taxonomy of
    constructions (CEFR, examples, prerequisites, common interferences) with a
    loader in `src/languages/`.
  - A deterministic grammar precision / false-correction benchmark
    (`benchmarks/grammar_bench.py`).

- **Phase 3 — Evidence pipeline.** A new `src/evidence/` subsystem that
  separates "what happened" from "what we believe about the learner":
  - Structured, immutable `LearningEvent` records with ten event types
    (`TURN_COMPLETED`, `GRAMMAR_ERROR`, `VOCAB_PRODUCED`, `REVIEW_RESULT`, ...),
    each carrying skill, item, observed/expected, assessment, confidence, and
    provenance.
  - An extract → normalize → deduplicate → persist pipeline (`extractor`,
    `normalizer`, `deduplicator`, `confidence`, `provenance`, `store`,
    `pipeline`), with per-type confidence scoring and construction/word
    normalization so duplicate observations collapse and rule names canonicalize.
  - `persist_session` now emits and stores events **first**, then derives the
    belief layer (vocabulary lexicon, grammar error taxonomy) from those events.

- **Phase 2 — Persistent memory.** SQLite is now the source of truth for learner
  state, with safe evolution:
  - A central schema owner and migration runner (`src/memory/schema.py`) keyed
    on `PRAGMA user_version`; `init_all()` provisions the full schema.
  - New canonical tables/stores: `profiles`, `sessions` (lifecycle + resume),
    `skill_states`, `learner_state_snapshots`, `evidence`, `assessments`,
    `experiments`/`experiment_assignments`, and `model_runs`.
  - Learner profiles are written through to SQLite (JSON kept as a readable
    mirror); session lifecycle is recorded so "quit, restart, resume" works and
    a later session surfaces reviews generated from prior evidence.
  - LLM telemetry is persisted to `model_runs` when enabled at startup.

- **Phase 1 — Provider abstraction.** Extended the LLM layer per the plan:
  - `LLMProvider` gains `generate_structured()`, `stream()`, and
    `count_tokens()` (non-abstract defaults; the frozen `generate()` contract is
    preserved).
  - `src/llm/schemas.py` — Pydantic response models + a tolerant
    `parse_structured` helper (returns `None` on invalid/malformed output),
    including a verifier decision model with explicit `abstain`.
  - `src/llm/telemetry.py` — per-call latency/token/cost records with an
    in-process buffer and pluggable durable sinks.
  - `src/llm/router.py` — task-oriented tiers (`critical_reasoning`,
    `fast_extraction`, `cheap_classification`, `local_private`) mapped onto the
    existing capability tiers, so routing by task doesn't break callers.
  - `src/llm/openai.py` — an OpenAI provider that joins the routing chain when a
    key is configured.

- **Phase 0 — Repository stabilization.** Made the project trustworthy before
  adding features:
  - Canonical developer workflow via `Makefile` (`make install/test/lint/format/typecheck/benchmark/health/check`).
  - Continuous integration (GitHub Actions) running lint, type-check, and tests on Python 3.12.
  - `.pre-commit-config.yaml` wiring ruff (lint + format) and mypy.
  - Dependency lockfile (`requirements.lock`) for reproducible installs.
  - Semantic-versioning single source of truth: `pyproject.toml` now derives
    its version dynamically from `src.__version__`; the API and health check
    report the same version.
  - `.env.example` validation: `Settings` verifies at least one usable LLM
    backend is configured (or a local/deterministic mode is active) and stays
    in sync with `.env.example`.
  - `polyglot health` CLI command and per-provider `health()` checks.
  - Deterministic test mode (`POLYGLOT_DETERMINISTIC=1`) with a canonical fake
    LLM provider, wired through `get_provider`, plus a root `tests/conftest.py`.
  - Benchmark harness (`benchmarks/`) runnable via `make benchmark`.
  - Architecture Decision Records under `docs/adr/`.

### Fixed

- Schema setup (`init_all` and the store `init_db` functions) ran on every
  store call: about 60 SQLite connections per review request. It now runs
  once per process per database; a review request is about 3× faster.
- `requirements.lock` had drifted far from the tested environment, and 13
  pinned packages had known vulnerabilities. It is regenerated from the
  tested environment: 11 of the 13 are fixed, and 2 are accepted with
  documented reasons.
- The frontend had no lockfile; `package-lock.json` is added.
- The test suite could write to the developer's real `./data` (tests that
  used the default database path). Every test process now gets a throw-away
  data directory, and backup sets and media under `data/` are git-ignored.

- **VAD on Python 3.13.** Voice-activity detection no longer uses
  `audioop`, which Python 3.13 removes (this was the source of the
  long-standing pytest warning).

- **API reviews never rescheduled.** `POST /api/v1/review/submit` only bumped
  a counter, so a word reviewed through the API stayed due forever. It now
  goes through `grade_review`: FSRS scheduling, evidence and the learner
  model. It also accepts an optional `rating` and a `mode`.
- **New words counted as recalled.** Meeting a word was recorded as a
  successful `Good` FSRS review. New cards are now unreviewed, so their first
  review is the first real retrieval. They are still first due ten minutes
  after the word is met.

- **Vocabulary parser crash on off-contract JSON.** When a model answered the
  vocabulary prompt with a bare JSON list, or with non-object items,
  `_parse_vocabulary_response` raised `AttributeError` and broke the turn. It
  now returns no words. Found by the real-model benchmark.

- New learners no longer get an unsupported CEFR level. `default_profile()`
  seeded "A2", `build_cefr_profile` fell back to "A2", the session log
  recorded the default as an estimate, and `polyglot experiment measure`
  recorded it as a pre-test outcome. All four now report "insufficient
  evidence" instead (ADR-0031).
- Repeated or duplicated evaluations no longer inflate mastery, and calling
  `persist_session` twice for the same session no longer double-counts its
  evidence.
- Words the vocabulary agent took from the tutor's reply are recorded as
  exposure, not as positive evidence that the learner can produce them.
- The CEFR profile persisted at the end of a session now includes that
  session's evidence. It used to be built before the evidence was recorded.
- Replaced placeholder `YOUR_USERNAME` repository URLs in `README.md`,
  `CONTRIBUTING.md`, and `pyproject.toml` with the real repository.
- Corrected documented CLI commands so they are executable (scenario ids such
  as `es_restaurant_ordering`, language-by-name usage).
- Conversation history no longer repeats in the model's prompt on every turn.
  The API, CLI, Gradio, and ablation turn runners resend the whole session
  state each turn, and the graph's checkpointer merged it into its saved copy
  via the `messages` add-reducer; they now use `compile_turn_graph()`, which
  has no checkpointer.
- The React app can now call the API from its own origin: new `CORS_ORIGINS`
  setting (defaults to the local Next.js dev server; empty disables CORS).
- `.env.example` no longer ships placeholder API keys (`sk-...`, `AIza...`),
  which a copied `.env` treated as configured providers.
- Local Ollama mode works on a fresh install: `langchain-ollama` is now a
  declared dependency (`langchain-community` no longer ships `ChatOllama`, so
  every local call failed), and the provider caps the context window
  (`OLLAMA_NUM_CTX`, default 8192) instead of letting Ollama reserve Llama
  3.1's full 128k context and run out of memory.
- Default models updated: `gemini-2.0-flash` was shut down on 2026-06-01
  (now `gemini-3.6-flash`) and `claude-sonnet-4-20250514` is deprecated (now
  `claude-sonnet-5-5`). The Claude provider no longer sends `temperature`,
  which current models and API version `2026-10-21` reject.
- `POLYGLOT_DETERMINISTIC=1` in `.env` now enables the offline demo; it was
  only read from the shell environment.
- Terminal chat (`polyglot chat`) now records learning evidence: it stopped
  each turn as soon as the reply arrived, so grammar/vocabulary analysis never
  ran and every CLI session reported no errors and no new words. The CLI and
  `src.main` now use the API's turn runner, which also applies adaptive
  difficulty.
- `polyglot health` now checks that a backend can actually answer (Ollama
  running, configured model pulled) and prints a `fix:` line, instead of
  reporting "Configuration OK" for an Ollama that isn't there. `polyglot chat`
  refuses to start without a working backend, and the Gradio app warns at
  launch.
- Errors that can't succeed on a retry (missing package, unknown model, bad
  key) fail over immediately instead of being retried.
- The CLI no longer crashes with `UnicodeEncodeError` on Windows consoles that
  aren't UTF-8, and httpx no longer logs every request into the chat.
- API: passwords over bcrypt's 72-byte limit return 400 instead of 500;
  usernames are trimmed and blank ones rejected; blank or over-2000-character
  chat messages are rejected before running an LLM turn.
- Docker: the Gradio UI listens on `0.0.0.0` so it is reachable from the host;
  the app containers reach the `local-llm` Ollama container; a `web` profile
  runs the React dashboard.
- `bcrypt` and `cryptography` are declared dependencies (they were imported
  but only installed transitively).
- The React app's `npm run lint` (an interactive ESLint setup prompt) is
  replaced by `npm run typecheck`.
- The grammar, vocabulary and cultural agents return no findings on a total
  LLM outage instead of raising, which crashed the CLI chat (and failed the
  API `/chat` turn) when no backend answered, e.g. with invalid API keys.
- Gemini's 4xx errors (such as an invalid key) are recognised as permanent
  and no longer retried; the status is read from the wrapped SDK error.
- `polyglot chat` prints replies verbatim: Rich treated `[word]` in a reply
  (and the offline demo's `[fake:...]` prefix) as markup and dropped it.
- The `httpx2` client used by current Anthropic/OpenAI SDKs and
  `google_genai` no longer log a line per request into the chat.

### Changed

- **Planner speaking activities.** The adaptive planner now proposes
  `speaking_check` for speaking and `read_aloud` for pronunciation, backed by
  the new assessments.

- **Review mode.** `grade_review` accepts `mode="recognition" | "production"`.
  - A recognition success is rated `Hard` for FSRS, and a production success
    keeps the learner's rating.
  - The mode is recorded as the evidence subskill and the mastery dimension.
  - Without a mode, the legacy behaviour is unchanged.

- **Evidence-driven learner knowledge model (ADR-0031).** The learner model is
  now a deterministic projection of immutable evidence that accounts for task
  difficulty and uncertainty.
  - Evidence records carry the skill, subskill, learning objective and item;
    the task type; the task difficulty in [0, 1], with an explicit
    `difficulty_basis` that keeps `unknown` apart from rated or measured
    values; and the prompt, rubric and model versions. They also carry a
    content fingerprint, a correlation id, and a `supersedes` link for
    corrections. Corrections go into a new append-only
    `evidence_supersessions` table and never edit a row.
  - New pure engine `src/learner/estimation.py` (`lkm-evidence-v2`): a
    weighted MAP Rasch-style ability for each skill.
    - Each observation is weighted by reliability, recency (relative to the
      skill's newest evidence, not the clock), a per-item repetition
      discount, and an unknown-difficulty discount.
    - Duplicate and correlated judgments merge into one observation, and
      exposure counts toward coverage only.
    - It reports mastery (`null` without graded evidence), an interval,
      uncertainty, an ordinal evidence index (explicitly not a probability),
      evidence quantity and quality, and coverage (practised, assessed,
      demonstrated, and coverage of the grammar-pack catalog). It also
      reports an evidence status (`insufficient_evidence` / `provisional` /
      `estimated` / `validated`), plus the old engine's value as
      `baseline_mastery`.
  - `KnowledgeModel.recompute` replays the active evidence in a stable order.
    It writes `skill_states` plus append-only `lkm_processing_runs` and
    `mastery_updates` only when the evidence digest changes, so processing is
    idempotent. `replay(run_id)` reproduces any past run, and `explain(skill)`
    lists each event's contribution.
  - The CEFR profile (`cefr-profile-v2`) is nullable and has explicit states:
    no default level, a band only at `provisional` or better, an overall band
    only when at least two skills are assessed, and unassessed skills listed
    rather than treated as weak.
  - The tutor's prompt level is now an explicit *working level*, separate
    from the assessed level. It is never seeded, and it is logged only when a
    session gives a signal. `user_profile.DEFAULT_WORKING_LEVEL` is used for
    prompts only.
  - The planner labels every action `assessment`, `remediation`,
    `reinforcement` or `advancement`, and recommends assessment, not
    remediation, when evidence is insufficient. Other changes:
    - Assessments are scored by information value and capped while learning
      actions still fit.
    - Readiness is blocked only by a prerequisite the evidence shows is weak.
    - Grammar coverage drives a `diagnostic_check` of the easiest
      unassessed construction.
    - FSRS scheduling is unchanged.
  - Migration 0007 is additive: new nullable or defaulted columns on
    `evidence`, `skill_states` and `assessments`, and three new tables.
    Existing rows are preserved, and legacy evidence replays into the new
    model.
  - API: CEFR, band and mastery are nullable; `status`, the interval, counts,
    coverage and `intent` fields are added; there are new
    `GET /api/v1/learner/explain/{skill}` and `GET /api/v1/learner/history`
    routes; and `insights` gains `overall_status` and `needs_assessment`.
  - Clients: the React types and `TodaysPlan` show "not yet assessed", the
    status, the mastery range and each action's intent. The dashboard labels
    the session value "Working level". Gradio has a "My level" panel.
    `polyglot assess` and `polyglot plan` show the status, interval and
    intent.
  - Privacy export now includes evidence, supersessions and the learner-model
    history, and deletion removes the history.

## [0.1.0] — Initial

### Added

- LangGraph orchestration with Conversation, Grammar, Vocabulary, SRS, Cultural,
  Evaluator, and Transfer agents.
- Multi-provider LLM abstraction (Claude / Gemini / Ollama) with tiered routing
  and failover.
- SQLite + ChromaDB memory layer, FSRS scheduling, YAML scenario engine.
- FastAPI REST API, Typer CLI, and Gradio UI entry points.

[Unreleased]: https://github.com/NiravRVaghasiya/Polyglot-Swarm/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/NiravRVaghasiya/Polyglot-Swarm/releases/tag/v0.1.0
