# 0036. Reply before analysis

- Status: Accepted
- Date: 2026-11-08
- Amends: [0035](0035-production-maturity.md) (durable sessions)

## Context

A chat turn ran the whole graph before answering: the conversation node,
then the grammar, vocabulary and cultural agents in parallel, then the
evaluator and the adaptive-difficulty step. The learner waited for about
three sequential layers of model calls, although only the first produces the
reply. With 600 ms per simulated model call, chat p95 at one learner was
1,428 ms. `run_turn`'s docstring claimed it stopped once the conversation
node replied; it did not.

The analysis still matters before the *next* turn: the evaluator's
difficulty signal pitches the next reply, and every turn's findings must reach
the evidence store in order, exactly once.

## Decision

- **Two graphs.** `src/orchestrator/graph.py` keeps the full graph (used by
  the ablation runner) and adds the analysis stage as its own graph
  (`build_analysis_graph`: grammar, vocabulary and cultural in parallel, then
  the evaluator). The reply stage is the full graph without analysis
  (`REPLY_COMPONENTS`); the turn runner stops it once the conversation node
  has replied.
- **Background analysis per session.** `src.api.sessions.run_turn` returns the
  reply, then runs the turn's analysis and the adaptive step as an asyncio
  task. The task inherits the turn's interaction id and its per-turn
  model-call cap.
- **Ordering.** Turn N+1 and finalization await turn N's analysis first
  (`wait_for_analysis`); a per-session lock serializes turns. Evidence,
  vocabulary and the report are therefore the same as in the synchronous
  flow (tested over a scripted five-turn session).
- **Atomic merge, durable mark.** Analysis results are merged into the state
  in one step when the analysis completes. Until then the snapshot carries
  `pending_analysis_turn`; a session rehydrated with it (after a restart or a
  cancelled task) re-runs that analysis before continuing. At shutdown the
  API waits up to 30 s for running analyses.
- **Failures.** An analysis failure is logged
  (`polyglot_session_events_total{event="analysis_failed"}`) and the turn's
  analysis skipped; the next turn proceeds.
- **API contract.** `hidden_feedback` on `POST /api/v1/chat` covers the turns
  analyzed before this one, and gains `through_turn` (how many). Turn N's
  feedback arrives with the response to turn N+1 and in the end-of-session
  report. The React app does not display hidden feedback; only its type
  changed.
- **Event loop hygiene.** SQLite work on the chat and session paths runs in
  worker threads (`asyncio.to_thread`): session lookups and snapshots,
  idempotency records, interaction links, session-cap checks, claims and
  finalization's persistence.
- **Other runners.** The CLI runs its session in one event loop, so analysis
  overlaps the learner typing; it now finalizes through
  `sessions.finalize`, which also marks its snapshot finalized. The Gradio UI
  runs one event loop per message, so it waits for the analysis before
  returning (unchanged latency there).

## Consequences

- The learner sees the reply after one model call instead of three layers.
  When the learner answers faster than the analysis takes, the next turn
  waits for the remainder, so the gain depends on think time. Measured at
  one learner with 600 ms per model call: chat p95 731 ms with a 3 s pause
  between turns, 1,391 ms with none (1,428 ms before). From about 10
  concurrent learners the background analyses compete for the one process
  and the gain disappears (`docs/production/performance-report.md`).
- Feedback is one turn behind in the chat response. Clients that show it per
  message must attach it to the previous turn (`through_turn`).
- The trace of a re-run analysis (after a restart) is recorded under a new
  interaction id, not the original turn's.
- Several API workers would still each hold their own background tasks; the
  single-process constraint of ADR-0035 is unchanged.
