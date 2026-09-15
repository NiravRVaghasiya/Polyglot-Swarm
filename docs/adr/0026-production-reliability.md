# 0026. Production reliability (Phase 23)

- Status: Accepted
- Date: 2026-09-15

## Context

The plan calls for retries with bounded backoff, circuit breakers, graceful
degradation, and health/readiness probes with structured logs. Before this
phase: `RoutingProvider.generate` tried each provider in its chain exactly
once and failed over immediately on any exception, with no memory of past
failures across calls — a provider that was actually down was retried fresh,
paying its full failure latency, on *every single turn* forever.
`conversation_node` had no exception handling at all around
`await provider.generate(...)`, so a total provider-chain outage crashed the
whole turn. `persist_session` called `analytics.record_error`/
`analytics.log_session` with no isolation, so an analytics-store failure
could prevent `sessions.end_session(status="completed")` and the
knowledge-model update that run afterward in the same function from ever
happening, even though the events that actually matter (evidence, vocabulary,
grammar taxonomy) were already durably written earlier in the function. The
voice pipeline's default TTS synthesizer had no fallback (unlike
`frontend/gradio_app.py`, which already degraded gracefully independently).
`GET /health` was a pure liveness check with no way to ask "can this process
actually serve a request right now." No module called
`logging.basicConfig` anywhere, so `polyglot.*` log records had no
configured handler in a bare process.

## Decision

- **A per-provider circuit breaker keyed by name, not by instance.**
  `src/llm/reliability.py`'s `CircuitBreaker` tracks consecutive failures per
  provider *name* in a module-level singleton
  (`default_circuit_breaker`), because `get_provider()` builds a fresh
  `RoutingProvider` (and fresh concrete provider objects) on every call —
  only state living outside any single `RoutingProvider` instance can
  remember "this provider has been failing" across separate turns. Rejected
  storing breaker state on `RoutingProvider` itself (would reset every
  call, defeating the purpose) and rejected a database-backed breaker
  (unjustified durability requirement for state that should reset on
  process restart anyway).
- **Retry is separate from, and precedes, failover.** `RetryPolicy`
  (`max_retries`, `base_delay`, `max_delay`, exponential backoff via
  `backoff_delay`) retries the *same* provider before giving up on it and
  moving to the next one in the chain. Default `max_retries=0` preserves the
  exact pre-Phase-23 behavior for any caller that builds a `RoutingProvider`
  directly without configuring retries (including every existing test) —
  retrying was made additive, not a forced behavior change.
- **Total-outage degradation is a canned, in-character reply, not an error
  message.** `conversation_node` catches any exception from the provider
  chain and returns a language-specific fallback line (framed as "I didn't
  hear you clearly," not a technical error) so a total LLM outage still
  reads as a plausible in-scenario turn rather than breaking immersion or
  leaking infrastructure details to the learner. Rejected surfacing a
  generic "an error occurred" message — that breaks character and is a
  worse experience than a slightly odd in-character line for what should be
  a rare event.
- **Analytics isolation is a try/except at the two call sites, not a
  generic "resilient store" wrapper.** `persist_session`'s calls to
  `analytics.record_error` and `analytics.log_session` are each wrapped
  individually (log and continue) rather than introducing a decorator or
  base-class pattern applied to every store call in the function — the
  other writes in that function (vocabulary, session history, session
  lifecycle, knowledge model) are the ones that must not be blocked by
  analytics, so scoping the try/except precisely to analytics keeps the
  failure boundary legible rather than hiding it behind an abstraction.
- **TTS fallback matches the pattern the Gradio frontend already used.**
  `src/speech/livekit_agent.py`'s default synthesizer now catches
  `SpeechDependencyError` and any other exception, returning empty audio
  (text-only) with a logged warning/error — the same shape
  `frontend/gradio_app.py`'s `synthesize_reply` already had independently.
  Rejected inventing a different fallback contract for the LiveKit path;
  consistency with the existing pattern was preferred over a "better"
  bespoke design.
- **`/ready` is a distinct endpoint from `/health`, not `/health` with more
  checks.** Keeping liveness and readiness separate follows the standard
  Kubernetes-style distinction: `/health` answers "is the process up"
  (always true if it can respond at all) and `/ready` answers "can this
  process serve a real request right now" (database reachable, at least one
  LLM tier available, vector store checked but not gating). The LLM check
  calls each tier's `.health()` — configuration only, no network call — so
  `/ready` is safe to poll frequently without generating real provider
  traffic. The vector store failure is reported as `degraded` but does not
  flip overall readiness, since it's an enrichment layer (semantic search
  over cultural notes) rather than required for the core chat/grammar/
  vocabulary path.
- **Logging config is one small module, applied at both entry points.**
  `src/observability/logging_config.py` provides `configure_logging`
  (idempotent — replaces handlers rather than stacking on repeated calls)
  and `ensure_configured`/`is_configured`. Both the CLI (`src/cli.py`, at
  import time) and the API server (`src/api/app.py`'s lifespan) call
  `ensure_configured()` so every entry point gets visible logs without
  forcing test code (which manages its own logging capture) to configure
  anything. JSON output (`log_format="json"`) is one `logging.Formatter`
  subclass, not a new logging library dependency.

## Consequences

- A provider that goes down is now tried, retried a bounded number of times,
  and then skipped entirely for a cooldown window — instead of paying its
  full failure cost on every subsequent turn forever. The trade-off accepted
  is a fixed cooldown (default 30s) during which a provider that has
  actually recovered is still skipped; acceptable since a single success
  during the half-open trial after cooldown fully closes the breaker again.
- A total LLM outage no longer crashes a conversation turn; the learner sees
  a plausible in-character line instead of an exception. This required no
  changes to `LearnerState`'s shape — the fallback path still returns the
  same `{"messages", "agent_response", "turn_count"}` update shape as the
  success path.
- An analytics-store outage can no longer prevent a session from being
  marked completed or the learner's skill beliefs from being updated —
  the two things that most matter for continuity across sessions.
- `/ready` gives an orchestrator (Kubernetes, Docker Compose healthchecks,
  a load balancer) a real signal distinct from "the process didn't crash" —
  operators should point readiness probes at `/ready`, not `/health`.
- Every `polyglot.*` logger now actually produces output by default in a
  bare process, in a format (`text` or `json`) controlled by settings rather
  than left to whatever the hosting environment happened to configure (or
  didn't).
- All of the above were additive: the full existing test suite
  (1001 tests as of this phase) passes unchanged, plus new tests added for
  the retry/breaker state machine, the degradation paths, and `/ready`.
