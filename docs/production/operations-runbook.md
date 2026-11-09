# Operations runbook

How to run Polyglot Swarm in staging and production, read its signals, and
respond to incidents. The decisions behind these mechanisms are in
[ADR-0035](../adr/0035-production-maturity.md); the objectives they protect
are in [service-objectives.md](service-objectives.md).

## Deploy

The deployment unit is one Docker image, run by
[`docker-compose.prod.yml`](../../docker-compose.prod.yml) on one host. It
starts the API (one uvicorn worker) and a nightly backup job. TLS
termination is a reverse proxy in front of `127.0.0.1:8000`.

1. **Configure.** Copy `.env.production.example` to `.env.production` on
   the host and fill in every `<...>`. Secrets stay on the host, never in
   the image or the repository.
2. **Validate.** Every problem is listed and the command exits 1:
   ```bash
   docker compose -f docker-compose.prod.yml run --rm api polyglot ops config-check
   ```
   The API also refuses to start with the same problems.
3. **Back up** before every deploy (migrations also take a pre-migration
   backup automatically):
   ```bash
   docker compose -f docker-compose.prod.yml exec api polyglot ops backup --label pre-deploy
   ```
4. **Deploy:**
   ```bash
   POLYGLOT_IMAGE_TAG=<git sha> docker compose -f docker-compose.prod.yml up -d --build
   ```
5. **Verify.** `GET /ready` returns 200 with `schema_version` equal to
   the code's version, and `polyglot ops db-check` passes. Then watch the
   5xx ratio and chat latency on the dashboard for 15 minutes.

**Staging** is the same file with `APP_ENV=staging`, its own env file and
its own project name, so it has its own volume:

```bash
POLYGLOT_ENV_FILE=.env.staging docker compose -f docker-compose.prod.yml -p polyglot-staging up -d --build
```

CI rehearses this on every push to main (the *Container · Staging rehearsal*
job): it builds the image, runs config-check and starts the container
read-only and non-root. It then checks `/ready`, that `/docs` is closed and
that `/metrics` needs its token, and backs up, verifies and restores inside
the container.

**Rehearsal record (2026-11-07, local Docker 29.5, image built from this
tree).** Every step passed:

- configuration:
  - an unsafe production configuration was refused;
  - the staging configuration was accepted;
- startup and security:
  - the container started read-only, as uid 10001, with all capabilities
    dropped;
  - it migrated to schema v10, and `/ready` returned 200;
  - `/docs` returned 404, and `/metrics` without its token returned 401;
  - HSTS, CSP and `X-Request-ID` were present;
- a learner journey with the LLM unreachable completed (chat degraded
  gracefully: 200);
- a container restart in the middle of a session kept the session
  (`turn_count` 1 after the restart);
- backup, verify, stop, restore and start succeeded, `ops db-check`
  passed, and the learner could log in after the restore;
- the access log was JSON lines with request ids.

### Rollback

Migrations are forward-only. Rolling back the code past a migration means
restoring data from before that migration.

| Situation | Action |
|---|---|
| New release misbehaves, **no migration** in it | redeploy the previous image tag |
| New release ran a migration | stop the API; `polyglot ops restore <pre-migration-vN set> --yes`; redeploy the previous image tag |
| Data damaged by a bug | stop the API; restore the newest good set; redeploy |

Data written after the restored backup is lost; that is the RPO (see
[Backups](#backups)).

## Signals

| Endpoint | Use |
|---|---|
| `GET /health` | liveness: the process answers |
| `GET /ready` | readiness: database reachable and on the expected schema, at least one LLM tier configured; the vector store may be `degraded` without failing readiness |
| `GET /metrics` | Prometheus metrics, with `Authorization: Bearer $METRICS_TOKEN` |

- **Logs.** In production these are JSON lines on stdout (Docker keeps
  5 × 20 MB per container). Every line carries `request_id` and, inside a
  chat turn, `interaction_id`. The `polyglot.access` logger writes one line
  per request: method, route template, status, duration. Logs never contain
  tokens, passwords, audio or transcripts. Learner messages are not logged,
  and user ids appear only in a few error lines (pseudonymous `u-…` ids).
- **Tracing one request.** Clients may send `X-Request-ID`; the server
  echoes it, or generates one, on every response, including 500s, whose
  body carries it too. Search the logs for that id.
- **Tracing one chat turn.** `GET /api/v1/trace/{session_id}` (owner only)
  reconstructs every model call and evidence event of a session.
- **Dashboards and alerts.** The Grafana dashboard is
  [`ops/grafana/polyglot-dashboard.json`](../../ops/grafana/polyglot-dashboard.json)
  and the alert rules are
  [`ops/prometheus/alerts.yml`](../../ops/prometheus/alerts.yml). A test
  checks that every metric they use exists and that every alert links to
  a section of this runbook.

## Incident severity and escalation

| Severity | Meaning | Response |
|---|---|---|
| **Sev1** | Learners cannot use the product (API down, data loss in progress) | Page the on-call now; status update every 30 min; postmortem required |
| **Sev2** | A core workflow is degraded (5xx above SLO, budgets exhausted, finalization failing, no backups) | On-call responds within 1 h during the day; postmortem if learner data was affected |
| **Sev3** | Degraded but tolerable (slow responses, fallback models, maintenance lag) | Next working day |

Escalation: on-call engineer, then the maintainer who owns the area (see
`CODEOWNERS` if present, otherwise the repository maintainers). A security
incident (a suspected credential leak, unauthorized access) is always Sev1
and follows [SECURITY.md](../../SECURITY.md): rotate the affected secret
first, then investigate.

For every incident: note the start time, the alert, the request ids; fix
or mitigate; record what learners saw and whether any learner data was
lost or wrong.

## Procedures

### API down

`PolyglotApiDown`; `/health` fails.

1. `docker compose -f docker-compose.prod.yml ps`, then `logs --tail 200 api`.
2. Crash on startup with "configuration problem" means a config change was
   rejected: fix `.env.production`, then run `ops config-check`.
3. Crash in migrations: the pre-migration backup exists. Restore it and
   redeploy the previous image (see [Rollback](#rollback)).
4. Out of memory: check `docker stats`; the limit is 2 GB.
5. No learner state is lost when the process dies: chat sessions are
   snapshotted after every turn and rehydrate on the next request.

### Elevated errors

`PolyglotHigh5xxRate`.

1. Find the failing routes:
   `sum by (route, status) (rate(polyglot_http_requests_total{status=~"5.."}[5m]))`.
2. Take a `request_id` from the access log and read its error log line.
3. `database is locked` errors mean write contention. Check that only one
   API process runs against the volume (see the capacity limits in
   [performance-report.md](performance-report.md)).
4. 503s from `/api/v1/voice/*` or the listening audio mean the speech
   extras or Edge TTS are down. Text workflows are unaffected.

### Slow responses

`PolyglotSlowApi`, `PolyglotSlowChat`.

1. Chat latency is dominated by LLM calls: compare with
   `polyglot_llm_latency_seconds` per provider.
2. If the LLM is fast but the API is slow, check concurrency against the
   measured capacity ([performance-report.md](performance-report.md)). The
   single process is CPU-bound around the throughput measured there.
3. Mitigations: lower `USER_RATE_LIMIT_PER_MINUTE`, scale the host up (more
   CPU per process). Do not add uvicorn workers (see the capacity section).

### Provider outage

`PolyglotLlmErrorRate`, `PolyglotLlmFallbackActive`.

- **What learners see.** Retries, the circuit breaker and failover handle
  short outages. If every provider fails, chat turns still complete with a
  generic in-character reply, and grammar and vocabulary analysis is
  skipped. No correctness evidence is invented: the turn is recorded only
  as exposure.
- **Fallback models.** Evidence produced while a fallback model answered
  carries `model_version` with `(fallback)`, so it can be found and, if
  needed, superseded later.
- **Actions:**
  - check the provider's status page;
  - check that the key is still valid (a `401` in `model_runs.error`);
  - for a long outage of the primary, temporarily set `LLM_PRIMARY` to a
    healthy provider and redeploy.

### Budget exhausted

`PolyglotBudgetRejections`, `PolyglotDailySpendHigh`.

- Learners get `429 {"code": "budget_exceeded"}` with a scope:
  - `user` — that learner reached their daily cap
    (`LLM_USER_DAILY_BUDGET_USD` / `LLM_USER_DAILY_CALLS`);
  - `global` — the whole deployment reached `LLM_GLOBAL_DAILY_BUDGET_USD`;
  - `turn` — a runaway loop was stopped (`LLM_MAX_CALLS_PER_TURN`).
- Budgets reset at 00:00 UTC.
- To raise a cap, change the env value and restart.
- Costs are *estimates* from token counts and the price table
  (`src/llm/telemetry.py`); reconcile with provider invoices monthly.
- Repeated `turn` rejections point to an agent bug: find the session with
  `GET /api/v1/trace/{session_id}`.

### Finalization failures

`PolyglotSessionFinalizeFailures`.

Ending a session runs end-of-session analysis and persists the session's
evidence. On failure the session stays `active` with its snapshot. The
maintenance task retries it once the session has been idle longer than
`SESSION_IDLE_FINALIZE_HOURS`, and a claim stuck in `finalizing` for over
an hour is released and retried.

1. Find the error in the logs (`polyglot.api.sessions`, "could not finalize").
2. Fix the cause (disk full, a provider error in the transfer step), then
   run `docker compose -f docker-compose.prod.yml exec api polyglot ops maintenance`.
3. A retry cannot double-count learner evidence: the learner model counts
   equal evidence fingerprints once. It can duplicate part of the turn log
   or analytics.

### Maintenance

`PolyglotMaintenanceNotRunning`.

The API runs maintenance every `MAINTENANCE_INTERVAL_SECONDS` (900 s by
default). It recovers idle sessions and purges expired tokens, expired
retained audio, old idempotency keys, old LLM-usage rows and rate-limiter
windows. Run it by hand with `polyglot ops maintenance`; the output reports
each step. A step that keeps failing shows as `{"error": ...}`.

### Speech assessment failures

`PolyglotAssessmentErrors`.

- `failed` with `unavailable`: Whisper is not installed in the image; the
  image installs runtime dependencies only. Install the `voice` extra in a
  derived image.
- `decoder_unavailable` (503): ffmpeg is missing.
- Abstentions are *not* failures. Silence, noise, a wrong language and a
  recogniser repetition loop all abstain by design (ADR-0034).

### Backups

`PolyglotBackupStale`, `PolyglotBackupMissing`.

- **What a set contains.** `polyglot ops backup` writes a set into
  `/data/backups/`: the SQLite database (online backup API, consistent
  while the app writes), retained media, profile files, and a manifest
  with SHA-256 checksums, the schema version and row counts.
- **Verification.** Each set is verified when written
  (`PRAGMA integrity_check` and checksums). `polyglot ops verify <set>`
  re-checks one at any time.
- **Schedule.** The `backup` service writes one set every
  `BACKUP_INTERVAL_SECONDS` (default 1 h, so RPO 1 h). Sets are kept on the
  host per `BACKUP_RETENTION_COUNT` (48, two days).
- **Off-host copies.** The `offsite` service copies them off the host,
  encrypted; see [Off-host copies](#off-host-copies).
- **Restore** (RTO target 1 h):
  ```bash
  docker compose -f docker-compose.prod.yml stop api backup
  docker compose -f docker-compose.prod.yml run --rm api polyglot ops backups
  docker compose -f docker-compose.prod.yml run --rm api polyglot ops restore /data/backups/<set> --yes
  docker compose -f docker-compose.prod.yml up -d
  ```
  The restore verifies the set first, takes a `pre-restore` safety backup
  of the current data, restores the database, media and profiles, and
  checks the row counts against the manifest.
- **Drills.** Restore verification is tested automatically:
  - `tests/test_production/test_backup_restore.py`, every CI run;
  - the container job, every push to main.

  Also run the off-host restore drill below in staging every month.
- **What is not backed up.** `chroma/` holds embeddings of static content.
  It is rebuilt on demand and is not learner data.

### Off-host copies

Alerts: `PolyglotOffsiteBackupStale`, `PolyglotOffsiteBackupMissing`.

The `offsite` service (`ops/backup/offsite-backup.sh` in the pinned
`restic/restic` image; ADR-0037) copies `/data/backups/` every
`OFFSITE_INTERVAL_SECONDS` (1 h) to `RESTIC_REPOSITORY`, a restic
repository on storage that is **not this host** (S3, B2, SFTP, a REST
server). restic encrypts on this host with `RESTIC_PASSWORD`, so the
storage provider never sees learner data. After each copy it applies the
retention policy (hourly for 24 h, then daily for 30 days), runs
`restic check`, and only then records success, which the API exports as
`polyglot_offsite_backup_last_success_timestamp_seconds`.

- **Setup.** Create the bucket or server account, put `RESTIC_REPOSITORY`,
  `RESTIC_PASSWORD` and the backend credentials in `.env.production`, and
  store `RESTIC_PASSWORD` in your password manager as well: **without it the
  copies cannot be decrypted**. `polyglot ops config-check` refuses to start
  staging/production without an off-host repository. The first run creates
  the repository.
- **Status.**
  ```bash
  docker compose -f docker-compose.prod.yml logs --tail 50 offsite
  docker compose -f docker-compose.prod.yml run --rm offsite snapshots
  ```
- **Failure** (`OFFSITE BACKUP FAILED` in the log, or the alert): check the
  backend credentials and reachability, then run one copy by hand:
  `docker compose -f docker-compose.prod.yml run --rm offsite once`. A
  wrong `RESTIC_PASSWORD` fails loudly; it never starts a second repository.
- **Restore from off-host** (the host or its volume is lost; RTO target
  2 h). On the new host, with the same `.env.production`:
  ```bash
  docker compose -f docker-compose.prod.yml run --rm offsite restore latest --target /data/offsite-restore
  docker compose -f docker-compose.prod.yml run --rm api polyglot ops verify /data/offsite-restore/data/backups/<newest set>
  docker compose -f docker-compose.prod.yml run --rm api polyglot ops restore /data/offsite-restore/data/backups/<newest set> --yes
  docker compose -f docker-compose.prod.yml up -d
  ```
  The CI container job runs exactly this against a throwaway REST server
  on every push to main.

### Data subject requests

Learners can export (`GET /api/v1/privacy/export`) and delete
(`DELETE /api/v1/privacy/data`) their own data in the web app, under
*Your data*; `polyglot privacy` serves requests that arrive by email. An
operator never
needs database access for this. Deletion does not reach backups. Backup
sets expire with retention (two days on the host, 30 days off-host),
which is the documented upper bound for erased data to persist (see
[security-privacy-review.md](security-privacy-review.md)).
