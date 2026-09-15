# Changelog

All notable changes to Polyglot Swarm are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

- Replaced placeholder `YOUR_USERNAME` repository URLs in `README.md`,
  `CONTRIBUTING.md`, and `pyproject.toml` with the real repository.
- Corrected documented CLI commands so they are executable (scenario ids such
  as `es_restaurant_ordering`, language-by-name usage).

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
