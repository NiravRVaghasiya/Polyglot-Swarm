# 0025. Cost and latency optimization (Phase 22)

- Status: Accepted
- Date: 2026-09-15

## Context

The plan calls for cost/latency visibility and reduction: which sessions and
turns are expensive, whether every LLM call needs the costliest model, and
whether static or repeated work is being redone unnecessarily. Before this
phase, every model call was already recorded by `src.llm.telemetry`
(latency, tokens, an estimated cost per call) but nothing aggregated those
records into a session- or user-level view; the evaluator agent always used
the "fast" tier regardless of what it was evaluating; `conversation_node`
sent the entire conversation transcript to the LLM on every turn, growing
cost and latency unboundedly with session length; and `src.scenarios.loader`
re-parsed a scenario's YAML file from disk on every single load, even though
scenario definitions are static, version-controlled content.

## Decision

- **Cost aggregation reuses existing storage.** `src/llm/cost.py`'s
  `CostSummary` and `session_cost`/`user_cost`/`turn_cost` are built entirely
  on top of `model_runs.get_runs_by_interaction_ids` plus the Phase 17
  observability link table (`interactions_for_session`/
  `interaction_ids_for_user`). Rejected adding new `session_id`/`user_id`
  columns to `model_runs` — that would duplicate the join logic the trace
  assembler already established, and the link table already answers "which
  interactions belong to this session/user" without a schema change.
- **Budget-aware tier escalation, not a new router.** The evaluator escalates
  from "fast" to "primary" only when `any(is_high_impact(e) for e in
  grammar_errors)` (`src.evaluation.policies.is_high_impact`, reused as-is).
  Rejected always using "primary" (defeats the cost savings) and rejected
  wiring up `src.llm.router`'s dead `TASK_TIER_MAP`/`resolve_tier` seam for
  this — direct tier escalation in the one agent that actually needs
  difficulty-based routing is simpler and sufficient; a generalized
  difficulty-aware router for every agent is not justified by the evidence
  that only the evaluator's decision quality benefits from it.
- **History windowing by simple truncation.** `conversation_node` caps the
  history it sends to the most recent `MAX_HISTORY_MESSAGES` (20) via a new
  `_windowed_history` helper. Rejected summarization-based compression (more
  complex, no existing infrastructure to build on) because the persona,
  objectives, and CEFR level — the durable context a role-play needs — are
  already re-rendered into the system prompt on every turn regardless of
  history length; only the *verbatim transcript* of what was said benefits
  from long-range recall, and role-play rarely needs more than the last
  several exchanges of that.
- **Scenario caching keyed by content, not just path.** `functools.lru_cache`
  wraps a new `_load_scenario_file_cached(path_str, mtime)`, with
  `load_scenario_file` stat-ing the file first and passing the mtime through.
  Rejected caching by path alone (would silently serve stale content after a
  scenario YAML edit during development) and rejected a file-watcher-based
  invalidation scheme (unjustified complexity for static content that
  changes only when a contributor edits a file on disk, not at runtime).
  Missing files are deliberately not cached — the `FileNotFoundError` is
  raised before the cached call, so a file that appears later (e.g. created
  after the process started) is picked up immediately rather than requiring
  a cache-clear.

## Consequences

- Cost/latency became something a user or operator can *see*
  (`polyglot cost session/user`, `GET /api/v1/cost/session/{id}`,
  `GET /api/v1/cost/me`) rather than only something recorded in a log line.
- The evaluator's average cost per turn drops for the common case (no
  high-impact grammar error), while turns that most need a stronger model's
  judgment still get one — a targeted trade-off rather than a blanket
  downgrade.
- A long-running conversation session no longer sends an ever-growing
  transcript to the model; the trade-off accepted is that very long-range
  callbacks (something said 30+ turns ago) are no longer visible to the
  conversation agent — acceptable because scenario role-play is built around
  recent context and explicit objectives, not long-range recall.
- Editing a scenario YAML file on disk (e.g. during scenario-authoring
  iteration) is picked up automatically on the next load, with no need to
  restart the process or manually clear a cache — `clear_scenario_cache()`
  exists for tests and any future hot-reload tooling that wants an explicit
  hook.
- None of these changes altered an existing test contract: budget-aware
  escalation, history windowing, and scenario caching were all additive
  changes to internal decision points, verified by the full existing
  `test_agents`/`test_graph`/`test_scenarios` suites passing unchanged plus
  new tests added alongside each change.
