# Service objectives

The service-level indicators (SLIs), the objectives (SLOs) for them, and the
recovery objectives that the operations runbook and the alert rules
(`ops/prometheus/alerts.yml`) are built on.

These targets suit a single-host deployment that serves a modest number of
learners. They are starting points, set from the measurements in
[performance-report.md](performance-report.md), not commitments to anyone.
Revisit them after a month of real traffic.

## Indicators and objectives

| SLI | Measured by | SLO (30-day window) |
|---|---|---|
| **Availability**: requests answered without a server error | `polyglot_http_requests_total`, status not 5xx, over all requests (4xx and 429 count as answered) | **99.5%** |
| **API latency** (non-LLM routes) | `polyglot_http_request_duration_seconds`, excluding chat, speaking and session end | **p95 < 500 ms** |
| **Chat-turn latency** | the same histogram, route `/api/v1/chat` | **p95 < 20 s** (provider-dominated; the alert fires above this) |
| **Session durability**: started sessions whose evidence reaches the learner model | `polyglot_session_events_total`: `finalized` over `started`, minus sessions still active | **100%** within `SESSION_IDLE_FINALIZE_HOURS` + 1 maintenance interval (about 6.25 h) |
| **No invented evidence**: LLM failures never produce graded evidence | automated tests (`test_reliability.py::TestOutages`) | **0** (a release blocker) |
| **Backup freshness**: age of the newest verified backup set | `polyglot_backup_last_success_timestamp_seconds` | **< 26 h** |
| **AI spend**: estimated daily spend versus the global budget | `polyglot_llm_cost_usd_total` | alert at 80%; hard stop at 100% (`LLM_GLOBAL_DAILY_BUDGET_USD`) |

**Error budget.** 0.5% of requests per 30 days. While the budget is
exhausted:

- freeze feature releases;
- ship only reliability fixes;
- write a postmortem for any single incident that used more than a quarter
  of the budget.

## Recovery objectives

| Objective | Target | How it is met |
|---|---|---|
| **RPO** (data loss window) | **1 h** for the whole data volume, including loss of the host; **0** for in-flight chat sessions after a process crash | hourly verified backup set, copied off-host (encrypted) hourly; per-turn session snapshots on the volume |
| **RTO** (time to restore service) | **1 h** after a volume loss with the host intact; **2 h** after losing the host; **minutes** after a process crash | `polyglot ops restore` from a local set, or from the off-host restic copy (runbook); container restart with rehydration |
| **Restore verification** | every backup verified when written; every off-host copy followed by `restic check`; local and off-host restore drills every push to main; manual staging drill monthly | `ops backup` verifies; `test_backup_restore.py`; CI container job |

An RPO below the backup interval would need continuous replication of the
SQLite file (for example Litestream). Shortening `BACKUP_INTERVAL_SECONDS`
and `OFFSITE_INTERVAL_SECONDS` is the cheaper first step.

## Critical workflows

These must keep working, possibly degraded, when optional services fail:

| Workflow | Depends on | When that fails |
|---|---|---|
| Sign up, log in, read progress and plans | API, SQLite | — (a hard dependency) |
| Chat practice | + an LLM provider | degraded reply; analysis skipped; no invented evidence; 429 on budget exhaustion |
| Review (FSRS) | API, SQLite | — (no LLM needed) |
| Listening | + Edge TTS (audio) | 503 for audio; answering and scoring still work |
| Speaking | + Whisper, ffmpeg | the assessment fails or abstains with a typed reason; nothing is recorded |
| Session end | + LLM (transfer step) | the claim is released; recovery retries later |
