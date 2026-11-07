# 0035. Production maturity baseline

- Status: Accepted
- Date: 2026-11-07
- Amends: [0024](0024-security-and-privacy.md) (security and privacy), [0025](0025-cost-and-latency-optimization.md) (cost), [0026](0026-production-reliability.md) (reliability), [0020](0020-observability-and-tracing.md) (observability)

## Context

The Phase 5 audit ([readiness-audit.md](../production/readiness-audit.md))
found a working development system with production gaps. The most severe:

- **Data loss.** Chat-session evidence was persisted only when the client
  ended the session, so a restart or an abandoned tab lost it.
- **No LLM timeout.** A hung provider could hold a worker for minutes.
- **Unbounded LLM spend.** There were no budgets or quotas.
- **Unverified backups.** Backups had no restore path and no check, and
  migrations ran with no backup first.
- **Unsafe exposure.** An unauthenticated Gradio UI was published, and
  production could start with development settings.
- **Thin observability.** There were no request ids, metrics, alerts or
  dashboards.

The rule for this phase was measurable risk reduction **without new
infrastructure that the risks do not require**.

## Decision

1. **Stay single-host and single-process.** SQLite (WAL) and one uvicorn
   worker remain the architecture. In-process state (the session cache,
   rate limiters, circuit breakers, metrics) is correct only with one
   process, so the image and compose pin `--workers 1`. Capacity is
   measured and documented instead of adding a broker, Redis or Postgres.
   The scaling thresholds that would justify them are in the performance
   report.
2. **Durable sessions.**
   - Every turn snapshots the session to `active_sessions`.
   - A request after a restart rehydrates it.
   - Maintenance finalizes idle sessions.
   - A conditional `active → finalizing` claim makes finalization
     exactly-once, and a failure releases the claim for retry.
   - Snapshots are cleared once finalized, and export and deletion cover
     them.
3. **LLM governance in the routing provider.**
   - **Timeouts:** each attempt has a timeout (retryable, then failover).
   - **Budgets:** per-user and global daily budgets in USD plus a call
     quota, kept in `llm_usage_daily`, and a per-turn call cap. A budget
     stop is never retried or failed over; the API answers `429
     budget_exceeded`.
   - **Provenance:** the answering model, marked `(fallback)` when it was
     not the tier's first choice, is recorded on the session's evidence as
     `model_version`.
4. **Idempotency keys** (`Idempotency-Key`) on the endpoints that record
   learning events: chat, review submission, speaking and listening.
5. **Environment profiles.** `APP_ENV=staging|production` fails fast on
   unsafe settings:
   - deterministic mode;
   - non-https or localhost CORS origins;
   - public API docs;
   - text logs;
   - a missing metrics token;
   - unbounded budgets;
   - telemetry off.
6. **Edge protections.** These are pure ASGI middleware:
   - request ids;
   - a structured access log;
   - a body-size limit;
   - security headers.

   Also: a JSON 500 handler, readiness that checks the schema version and
   never echoes exception text, a per-user work rate limit, and a minimum
   password length.
7. **Observability without an agent.**
   - **Metrics:** a dependency-free Prometheus registry at `/metrics`,
     behind a token. Label values are route templates, never ids.
   - **Alerts and dashboard:** alert rules and a Grafana dashboard live in
     `ops/`. A test checks that every metric they reference exists and that
     every alert links to a runbook section.
8. **Backups as verified sets.**
   - **Contents:** database, media and profiles, with a manifest of
     checksums, the schema version and row counts.
   - **Verification and restore:** sets are verified when written, and
     restore runs through the SQLite backup API after a safety backup.
   - **Schedule:** pre-migration backups are automatic, plus a nightly
     backup service, retention, and `polyglot ops` commands.
9. **Supply chain.**
   - **Lockfiles:** the Python lock is regenerated from the tested
     environment and used as a constraints file; an npm lockfile is added.
   - **CI scans:** pip-audit runs against a version-pinned acceptance list
     with review dates, alongside a secret scan and the ruff `S` rules.
   - **Container:** non-root with a read-only root filesystem.
   - **Staging rehearsal:** a CI job builds the image and rehearses
     staging, including backup and restore.
10. **Performance fix from profiling.** Schema setup ran on every store
    call, about 60 SQLite connections per review request. It now runs once
    per process per database (`once_per_database`).

## Consequences

- **Learner state survives crashes, restarts and abandoned sessions.** The
  RPO for in-flight sessions is 0. The RPO for the whole volume is 24 h,
  and less needs continuous replication (Litestream), the first follow-up.
- **AI cost is bounded per learner and per deployment.** Costs are
  estimates from the price table, not invoices.
- **Horizontal scaling is not supported.** Running more than one API
  process against the same volume breaks:
  - the session cache;
  - rate limits;
  - budgets' read-then-write window;
  - metrics.

  The documented path is a larger host first; beyond that, see the
  thresholds in the performance report.
- **Accepted residual risks** are listed in the risk register:
  - `localStorage` tokens, mitigated by CSP `connect-src`;
  - pillow and chromadb advisories with no compatible fix;
  - the PostCSS advisory inside Next;
  - backups are not encrypted by the application;
  - no compliance assessment has been done.
