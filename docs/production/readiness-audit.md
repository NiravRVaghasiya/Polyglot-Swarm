# Production readiness audit (Phase 5)

Audit date: 2026-11-07. Scope: the FastAPI service, the React app, the
Gradio UI, SQLite storage, LLM and speech providers, the container and
Compose setup, and CI. This document is the risk register: every
Phase 5 change refers to a risk id here, and the **Status** column records
the outcome. [ADR-0035](../adr/0035-production-maturity.md) records the
decisions.

## Architecture as deployed

```
browser ─► Next.js app ─► FastAPI (uvicorn, 1 process) ─► SQLite (WAL) + ChromaDB + files
                                │                        (one data volume)
                                ├─► LLM providers: Claude / Gemini / OpenAI / Ollama
                                │     (routing chain, retries, circuit breaker)
                                ├─► local Whisper (speech-to-text)
                                └─► Edge TTS (listening audio, voice replies)
Gradio UI ─► the same code in-process, sharing the data volume
```

- **State.** All durable state is in one SQLite file and its sibling
  directories (`chroma/`, `user_profiles/`, `media/`).
  - Active chat sessions were held only in process memory (see R1).
  - Rate-limit counters and circuit breakers are in process memory.
- **Background work.** There is no job runner. The work that could be
  interrupted:
  - session finalization (`/sessions/{id}/end`);
  - media retention purging (on each speaking submission);
  - token purging (never run).
- **Deployment.** One Docker image, run by Compose as `api` and `ui`, with
  an optional `web` (Next.js) and `ollama`. There is no staging or
  production profile.

## Critical dependencies and failure modes

| Dependency | Failure | Behaviour before Phase 5 |
|---|---|---|
| Hosted LLM APIs | outage, rate limit, slow response | retries + breaker + failover, but **no request timeout** (SDK defaults allow up to about 10 minutes) |
| Ollama (local LLM) | not running | marked unavailable by configuration only; calls fail and fail over |
| SQLite | disk full, corruption, lock contention | 5 s lock timeout; no verified backups |
| Whisper / ffmpeg | missing, slow | speaking abstains or fails with a typed error (Phase 4) |
| Edge TTS | outage | listening audio returns 503; text workflows unaffected |
| Process restart | deploy, crash | **in-flight chat sessions and their learning evidence lost** |

## Risk register

Severity reflects learner impact × likelihood in a single-host deployment
with real learners.

| Id | Severity | Area | Finding | Remediation | Status |
|---|---|---|---|---|---|
| R1 | Critical | Data loss | Chat-session evidence, vocabulary and the turn log were persisted only when the client called `/sessions/{id}/end`. A restart, crash or abandoned tab lost the whole session. Finalizing twice was not guarded. | Durable per-turn session snapshots; rehydration after restart; recovery that finalizes idle sessions; a `finalizing` claim so a session is finalized once | **Fixed**: snapshots, rehydration, recovery, claims (`test_reliability.py::TestDurableSessions`; container restart in the staging rehearsal) |
| R2 | Critical | Reliability / cost | No timeout on LLM calls; a hung provider holds a worker for minutes. | Per-attempt timeout (retryable), surfaced in telemetry | **Fixed**: `LLM_TIMEOUT_SECONDS` per attempt (`test_a_hung_provider_times_out_and_fails_over`) |
| R3 | High | Cost / abuse | No per-user or global LLM budget, no quota, no rate limit on LLM or upload endpoints; the only loop guard was LangGraph's recursion limit. | Per-user and global daily budgets, a per-turn call cap, per-user rate limits, typed 429s | **Fixed**: budgets, quotas, turn cap, per-user rate limit (`TestBudgets`, `test_per_user_work_rate_limit`) |
| R4 | High | Data loss | Backups were manual, never verified, had no restore path or retention, and covered only the SQLite file. Migrations ran at startup with no backup first. | Verified backup sets (database + media + profiles), restore, retention, a pre-migration backup, and a tested restore drill | **Fixed**: verified sets, restore, retention, pre-migration backup, nightly job (`test_backup_restore.py`, staging rehearsal). The off-host copy is an operator procedure (runbook). |
| R5 | High | Security | The Gradio UI (published on :7860 by Compose) has no authentication; anyone who can reach it uses the operator's LLM budget. | The production profile does not run it; it refuses to start in production without `GRADIO_AUTH` | **Fixed**: not in the production profile; refuses to start without `GRADIO_AUTH` |
| R6 | High | Security / DoS | No request-body size limit (JSON bodies were unbounded). | Body-size middleware (413) | **Fixed**: `MAX_REQUEST_BYTES` (413) |
| R7 | Medium | DoS | Unbounded active sessions per user; unbounded rate-limiter memory. | Per-user active-session cap; idle eviction; limiter pruning | **Fixed**: session cap with eviction, limiter pruning |
| R8 | Medium | Security | No minimum password length; no security headers; the browser stores a 30-day bearer token in `localStorage` with no CSP. | Minimum length 8 for new passwords; security headers on the API; CSP and headers on the Next app | **Mitigated**: minimum length 8; API and web headers; CSP `connect-src`. The token stays in `localStorage` (residual RR1). |
| R9 | Medium | Operations | No per-request correlation id, access log, metrics or alert definitions; readiness responses echoed raw exception text. | Request-id middleware, structured access log, `/metrics`, alert rules, dashboard, sanitized readiness | **Fixed**: request ids, access log, `/metrics`, alerts, dashboard, runbook (`test_observability.py`) |
| R10 | Medium | Configuration | No environment profiles: production could start in deterministic mode, with permissive CORS, public API docs and text logs. | `APP_ENV` with fail-fast production validation | **Fixed**: `APP_ENV` fail-fast and `ops config-check` (`TestProductionConfiguration`, staging rehearsal) |
| R11 | Medium | Supply chain | The container runs as root and is not built from the lockfile; CI has no dependency, static-security or secret scanning; `ollama:latest` is unpinned. | Non-root, lockfile build, pip-audit, ruff security rules, a secret scan, npm audit, a container build in CI | **Mitigated**: non-root read-only container, locked builds, CI scans. 2 accepted Python advisories (RR2) and 1 npm advisory (RR3). |
| R12 | Medium | Evidence quality | Provider fallback silently changes the model behind agent judgments, and chat evidence did not record the model. | Record the answering model on evidence; count fallbacks | **Mitigated**: fallback models recorded on evidence and counted. Their evidence keeps the same confidence (RR6). |
| R13 | Medium | Duplicates | A client retry of `POST /review/submit` or a listening submission records it twice (for example, two FSRS reviews). | `Idempotency-Key` support on mutating learning endpoints | **Fixed**: `Idempotency-Key` (`TestIdempotency`) |
| R14 | Low | Scalability | SQLite (single writer) and in-process state require a single API process. | Measured and documented capacity and scaling thresholds; accepted for now | **Measured**: capacity documented (`performance-report.md`); single process accepted (RR4) |
| R15 | Low | Hygiene | Expired tokens were never purged. | Purged by the maintenance task | **Fixed**: maintenance purges expired tokens |
| R16 | Low | Change safety | Migrations are forward-only, with no check command. | `polyglot db check`, a pre-migration backup; rollback means restoring | **Fixed**: `ops db-check`, pre-migration backups, rollback by restore (`TestMigrationSafety`) |
| R17 | Medium | Privacy | Learner messages are sent to hosted LLM providers by design; that handling was not documented per provider, and there is no compliance assessment. | Documented data flows and classification; no compliance claim | **Documented**: data flows and classification (`security-privacy-review.md`). No compliance assessment was done (RR5). |

## Residual risks (prioritised)

These remain open after Phase 5. None is a known data-loss or
access-control defect, but the first two must be resolved, or explicitly
accepted by the operator, before real learners use the system.

| Id | Severity | Risk | Mitigation now | Follow-up |
|---|---|---|---|---|
| RR5 | High | **No legal or regulatory assessment**: GDPR/UK GDPR, minors (COPPA, age-appropriate design), voice data | data minimised, in-app export and deletion, `LOCAL_ONLY` mode | an assessment by qualified counsel before launch; decide whether minors are admitted |
| RR7 | High | **Backups are on the same volume and unencrypted by the app**; RPO 24 h | verified nightly sets; the runbook requires daily off-host copies to encrypted storage | automate the off-host copy; continuous replication (Litestream) for RPO near 0 |
| RR1 | Medium | Bearer token in `localStorage` (30-day TTL by default) | CSP `connect-src` limits exfiltration; production template sets 7 days | move to `HttpOnly` cookie sessions with CSRF protection |
| RR6 | Medium | Evidence produced by a fallback model keeps full confidence | `model_version` marks it `(fallback)`; `PolyglotLlmFallbackActive` alert | discount or quarantine fallback evidence using Phase 2 per-model results |
| RR4 | Medium | Single process: about 12 req/s saturation; speech assessment (about 5 s CPU) blocks the worker | rate limits; scaling thresholds; alerts | move speaking assessment to a background worker; shared state before multiple replicas |
| RR2 | Medium | pillow 12.3.0 (39 advisories) pinned by gradio; chromadb 1.5.9 (no fix) | Gradio not deployed; Chroma embedded only; acceptances expire 2027-01-31 | upgrade when compatible releases exist |
| RR3 | Low | PostCSS advisory inside Next.js build tooling (high, build-time) | it affects build-time CSS processing only; `npm audit` blocks on critical | upgrade Next to the fixed major |
| RR8 | Low | Budget checks are read-then-write: concurrent calls can overshoot a cap by a few calls | small overshoot; global cap and alerts | an atomic reservation if caps get tight |
| RR9 | Low | Cost figures are token-estimate × price table, not invoices | the daily-spend alert fires at 80% | reconcile monthly with provider invoices |
| RR10 | Low | Image size is 4.35 GB (ChromaDB/ONNX, Gradio) | — | slimmer runtime image without the Gradio UI |

## What was already in place (verified, kept)

- **Authentication.** bcrypt passwords; tokens are random, stored only as
  hashes, and expire; login and registration are rate-limited.
- **Authorization.** Every API route requires authentication, and every
  data read is scoped to the caller's user id. Sessions are looked up by
  `(user_id, session_id)`. Cost and trace lookups take the caller's id.
- **Privacy.** Export and deletion cover every user table, including Phase 4
  media submissions; raw audio is not retained by default.
- **LLM reliability.** Retries with exponential backoff, a per-provider
  circuit breaker, failover across the chain, and per-call telemetry
  (`model_runs`: latency, tokens, cost, errors).
- **Evidence.** Evidence inserts are idempotent on `event_id`, and the
  learner model counts equal fingerprints once.
- **Git history.** No committed credentials were found (scan for provider
  key formats and private keys); `.env` is ignored.
