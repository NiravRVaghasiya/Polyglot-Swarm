# Performance and capacity report

Measured 2026-11-07 with [`ops/loadtest.py`](../../ops/loadtest.py), and
re-measured 2026-11-08 after chat turns started replying before their
analysis (ADR-0036). The raw results of the latest run are in
[`loadtest-results.json`](loadtest-results.json).

## Method

- **Server.** The real API process: `uvicorn src.api.app:app --workers 1`,
  as in production, on a fresh SQLite database.
- **Host.** Windows 11 with 8 logical CPUs. The load generator ran on the
  same host, so absolute numbers are conservative for a dedicated server.
- **Journey.** Each virtual learner repeats a complete journey with no
  think time. The steps:
  1. learner plan;
  2. start a session;
  3. three chat turns;
  4. due reviews;
  5. submit a review;
  6. progress overview;
  7. end the session.
- **LLM.** The deterministic fake provider, so these numbers measure the
  **application** and not a real model. Two settings:
  - 0 ms latency (pure application cost);
  - 600 ms simulated latency per model call (about five calls per chat
    turn), so concurrent turns wait the way they would on a real provider.
- **Load.** Concurrency 1, 5, 10, 25 and 50 learners, two journeys each.
- **Think time** (2026-11-08 run). A chat turn's analysis now runs after its
  reply, and the next turn waits for it. The run therefore uses two pauses
  between chat turns: 0 ms (the journey above, unchanged) and 3,000 ms (the
  learner reads the reply and types).

## Results

Each cell is p95 latency in ms. "Non-LLM" covers every route except chat
and session end.

### Reply before analysis (2026-11-08)

Chat latency with 600 ms per simulated model call:

| Concurrent learners | Chat p95 before (no pause) | Chat p95, no pause | Chat p95, 3 s pause | Session-end p95, 3 s pause |
|---|---|---|---|---|
| 1 | 1 428 | 1 391 | **731** | 758 |
| 5 | 1 725 | 1 718 | **823** | 1 308 |
| 10 | 2 116 | 2 142 | 2 644 | 2 633 |
| 25 | 4 305 | 3 948 | 3 746 | 3 513 |
| 50 | 7 881 | 9 853 | 11 378 | 9 820 |

- **With a pause, the reply arrives after one model call.** At one learner,
  chat p95 falls from 1,428 ms to 731 ms (p50 704 ms): the 600 ms
  conversation call plus about 130 ms of application time. The analysis runs
  while the learner reads and types.
- **Without a pause there is no gain** (1,391 ms). Turn N+1 waits for the rest
  of turn N's analysis before it starts, so the next reply absorbs it. Only
  the first turn of a session is faster.
- **Under load the gain disappears.** From 10 concurrent learners, the
  background analyses compete with requests for the one process, and the
  3-second-pause run was slower than the no-pause run at 10 and 50 learners
  (one run each; the cause was not investigated). Capacity is unchanged:
  the process is CPU-bound either way.
- **Session end** now includes waiting for the last turn's analysis.
- All 6,552 requests of this run succeeded.

### Before reply-first (2026-11-07)

| LLM latency | Concurrent learners | Throughput (req/s) | Journeys/min | Errors | Non-LLM p95 | Chat p95 | Session-end p95 |
|---|---|---|---|---|---|---|---|
| 0 ms | 1 | 10.6 | 71 | 0% | 240 | 175 | 196 |
| 0 ms | 5 | 13.1 | 88 | 0% | 520 | 573 | 664 |
| 0 ms | 10 | 12.7 | 85 | 0% | 1 137 | 1 326 | 903 |
| 0 ms | 25 | 12.1 | 81 | 0% | 3 813 | 3 855 | 4 731 |
| 0 ms | 50 | 12.1 | 81 | 0% | 5 934 | 7 641 | 5 110 |
| 600 ms | 1 | 2.0 | 14 | 0% | 68 | 1 428 | 163 |
| 600 ms | 5 | 7.1 | 48 | 0% | 568 | 1 725 | 440 |
| 600 ms | 10 | 10.2 | 68 | 0% | 699 | 2 116 | 1 793 |
| 600 ms | 25 | 12.4 | 82 | 0% | 2 253 | 4 305 | 2 592 |
| 600 ms | 50 | 11.9 | 79 | 0% | 6 020 | 7 881 | 5 833 |

All 3,276 requests succeeded. No `database is locked` errors occurred at 50
concurrent learners. The 2026-11-08 run (0 ms latency, no pause) gave 9.9 to
15.4 req/s, the same saturation range.

## Bottleneck found and fixed

The first runs saturated at **about 5 req/s**, with a single review
submission taking 250–290 ms. Profiling showed why: every store call re-ran
the whole schema setup (`schema.init_all()` and the stores' `init_db()`
DDL), about 10 times and 60+ SQLite connections per review request, which
was about 70% of its time.

Schema setup now runs once per process per database
(`src/memory/db.py::once_per_database`). The effect:

- a review is about 3× faster: 288 ms → 87 ms, profiled in-process;
- saturated throughput **more than doubled**, to about 12–13 req/s.

## Capacity and limits

- **Saturation.** One API process saturates at **about 12 req/s, about 80
  complete learner journeys per minute**. Throughput is flat above about
  5–10 concurrent zero-think-time learners, while latency grows linearly.
  The process is CPU-bound (Python, one process), not I/O-bound.
- **The latency objective.** Non-LLM p95 < 500 ms holds up to **about 5
  concurrently active zero-think-time learners**. The test just exceeds it
  at 5 (520 and 568 ms).
- **Translated to real use.** This is an estimate, not a measurement. A real
  learner pauses between actions: reading, typing, reviewing. A 10-minute
  study session generates about 10–20 requests, about 0.02–0.03 req/s per
  learner. At 50% utilisation (about 6 req/s, inside the SLO) one host
  serves **roughly 200–300 concurrently studying learners**. Validate this
  against real traffic from the dashboard before relying on it.
- **Memory.** Not measured in this run: the measurement library was not
  installed. The production compose sets a 2 GB limit; watch container
  memory on the dashboard host.

### Scaling thresholds

| Signal | Threshold | Action |
|---|---|---|
| Sustained throughput | above about 6 req/s (50% of saturation) | scale the host up: faster CPU |
| Non-LLM p95 | above 500 ms for 15 min (the `PolyglotSlowApi` alert) | check what is driving the load; scale up; lower `USER_RATE_LIMIT_PER_MINUTE` |
| Beyond one large host | about 12 req/s sustained | **architecture change.** Move shared state (session cache, rate limits, budgets, metrics) out of the process and SQLite to a server database. Only then run several workers or replicas. Not justified at current scale. |

**Do not add uvicorn workers** against the same volume. In-process state
(session cache, rate limiters, circuit breakers, metrics) would split
across workers, and SQLite allows one writer.

## Not covered

- **Real LLM latency and variance.** Chat-turn latency in production is
  dominated by the provider. `polyglot_llm_latency_seconds` shows it per
  provider.
- **Speech assessment under load.** Whisper on CPU takes about 5 s per
  utterance (ADR-0034). A burst of speaking submissions would saturate the
  process. Speaking assessment should move to a background worker before
  speech is offered at scale (a follow-up).
- **Long-running soak tests** (memory growth over days) and **frontend
  performance** (the production build's first-load JS is 103–218 kB per
  route).
