# 0020. Observability: interaction correlation and turn tracing (Phase 17)

- Status: Accepted
- Date: 2026-09-14

## Context

Two durable signals already existed describing what the tutor did: LLM-call
telemetry (`model_runs`, Phase 2/3) and structured evidence events (`evidence`,
Phase 3). Both already had an `interaction_id` column, but nothing ever
populated it — `RoutingProvider._record` built every `ModelRun` without one,
and every `LearningEvent`'s `Provenance` left it `None`. Without a shared
correlation key, a bad tutor response could not be reconstructed end-to-end:
which model call produced it, what evidence it generated, in what order.

The natural place to carry that id — a contextvar bound for the duration of a
turn — is complicated by one fact discovered during implementation:
turn-derived evidence (`GRAMMAR_ERROR`, `VOCAB_PRODUCED`, `TURN_COMPLETED`) is
built and persisted at **session end** (`persist_session`), aggregated across
every turn in the session, not per-turn during `run_turn`. A contextvar read at
that point would be unset, and even if it weren't, one id could not correctly
be attributed to many turns' worth of aggregated events.

## Decision

- Add `src/observability/context.py`: a `ContextVar`-based
  `interaction_scope(session_id=, interaction_id=)` that binds the current
  interaction (generating one if not supplied) for the duration of a block,
  propagating across `await` boundaries and restoring the previous value on
  exit (nesting-safe). `src.api.sessions.run_turn` wraps the whole turn in this
  scope.
- `RoutingProvider._record` (`src/llm/factory.py`) stamps
  `interaction_id=current_interaction()` on every `ModelRun` — a lazy import to
  avoid a cycle with the observability package.
- `LearningEvent.create` (`src/evidence/events.py`) falls back to
  `current_interaction()` when its `Provenance` did not supply one, so any
  evidence built *while a scope is active* is correlated automatically. This
  covers evidence built during a turn (e.g. SRS review results) but not the
  session-end aggregate evidence, which runs outside any scope by construction
  (see Context).
- To still correlate a session's `model_runs` (which carry no session column)
  even when no evidence coincides with a given turn, add a small
  `session_interactions` link table (migration 0004) and
  `src/observability/links.py`: `run_turn` records `(session_id,
  interaction_id, user_id, turn_index)` for every turn, independent of whether
  that turn produced evidence.
- `src/observability/trace.py` `assemble_trace(user_id, session_id)` reads a
  session's evidence (already filtered by `session_id`) and unions the
  interaction ids referenced there with the ids in `session_interactions`
  (filtered by `user_id` — see Security below), then pulls every `model_runs`
  row whose `interaction_id` is in that set. The result is a `Trace`: spans
  ordered by timestamp, grouped by interaction. `format_trace` renders it as
  ASCII-only text (no unicode glyphs, since the CLI must print cleanly on
  Windows cp1252 consoles).
- Expose `GET /api/v1/trace/{session_id}` (auth-scoped) and a `polyglot trace`
  CLI command.

## Consequences

- A turn is now reconstructable: `polyglot trace <session_id>` or the API route
  shows every LLM call and evidence event for a session, correlated and
  ordered.
- Because `model_runs` has no user/session column, `interactions_for_session`
  accepts an optional `user_id` filter and the trace route always passes it —
  without this, one user could reconstruct another user's LLM-call telemetry
  (provider, latency, tokens, cost) by supplying a known or guessed
  `session_id`. This was caught and fixed during implementation, not assumed
  safe by default.
- Per-turn evidence (grammar/vocabulary/turn-completed) still cannot be
  attributed to the exact interaction that produced it, because it is built
  once at session end from accumulated state. Making that fully precise would
  require moving evidence extraction into `run_turn` itself (a larger,
  separate change) — out of scope here; the `session_interactions` link table
  is what makes the trace still useful in the meantime by correlating at the
  session/turn-count level even without per-turn evidence.
- No new dependency (e.g. OpenTelemetry) was introduced; the trace reuses the
  Phase 2/3 storage that already existed.

