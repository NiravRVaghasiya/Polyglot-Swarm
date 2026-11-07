# Architecture

This document describes how Polyglot Swarm is actually built today. For the
original research and product framing, see [`DESIGN.md`](DESIGN.md); for the
decision-by-decision history, see the [ADR log](adr/README.md).

## Overview

A learner turn flows through a LangGraph state machine (`src/orchestrator/`):
one shared `LearnerState` TypedDict is threaded through a graph of agent
nodes, each of which reads what it needs from the state and returns a partial
update. No agent talks to another agent directly — everything is mediated by
the graph and the state.

```
User input
    │
    ▼
router  ──▶ conversation, or a review mode, or session end
    │
    ▼
conversation_node  ──▶ persona-driven reply (LLM, "primary" tier)
    │                  ── the reply is returned to the learner here ──
    │  (background task, awaited before the next turn and at session end)
    ├──▶ grammar_node     (silent error detection, "fast" tier, JSON mode)
    ├──▶ vocabulary_node  (new-word extraction, "fast" tier, JSON mode)
    └──▶ cultural_node    (register/idiom notes, confidence-gated)
    │
    ▼
evaluator_node  ──▶ QA pass: accept/revise/abstain on grammar errors,
                    difficulty assessment, budget-aware tier escalation
    │
    ▼
adaptive step  ──▶ pitch for the next turn
```

The turn runner (`src/api/sessions.py`, ADR
[0036](adr/0036-reply-before-analysis.md)) runs the reply stage, returns the
reply, and runs the analysis stage (`build_analysis_graph`) as a per-session
background task. The next turn and finalization wait for it, so every turn is
analyzed in order; the chat response's hidden feedback therefore covers the
turns before it.

At session end, `src/orchestrator/lifecycle.py`'s `finalize_session` runs the
assessment and transfer agents, then `persist_session` writes everything to
durable storage and builds the end-of-session report.

## Layers

**Agents** (`src/agents/`) — one module per concern (conversation, grammar,
vocabulary, cultural, evaluator, transfer, assessment, drills, peer, writing,
ingestion, review, srs). Each agent is a plain async function
`(state) -> dict` — independently testable with a fake `LLMProvider`, no
framework coupling beyond the state's shape.

**Orchestration** (`src/orchestrator/`) — `graph.py` builds the LangGraph
`StateGraph` (including an ablation-arm variant for learning-science
experiments, `build_ablation_graph`); `state.py` defines `LearnerState`;
`lifecycle.py` bridges the graph to persistence (`build_initial_state`,
`persist_session`, `finalize_session`).

**LLM layer** (`src/llm/`) — every agent asks for a *tier* ("primary",
"fast", "local", or a task-oriented alias resolved by `router.py`), never a
concrete vendor. `factory.py`'s `RoutingProvider` builds an ordered fallback
chain, retries a flaky provider with backoff, trips a circuit breaker for one
that's actually down, and fails over to the next. See
[`providers.md`](providers.md) for the full picture.

**Memory** (`src/memory/`) — SQLite is the source of truth for everything
relational (profiles, vocabulary, grammar error patterns, sessions, skill
beliefs, model-run telemetry, auth, audit log); ChromaDB
(`vector_store.py`) holds four semantic-search collections (vocabulary,
grammar_rules, conversations, cultural_notes). `src/memory/schema.py` owns
migrations (additive-only).

**Evidence and learner model** (`src/evidence/`, `src/learner/`,
`src/adaptive/`, `src/assessment/`) — see [`learner-model.md`](learner-model.md)
and [`adaptive-learning.md`](adaptive-learning.md). The layers, from data to
decision:

| layer | module | role |
|---|---|---|
| evidence | `src/evidence/store.py` | the record of truth: append-only learning events |
| skill engine | `src/learner/estimation.py` (`lkm-evidence-v2`) | pure function from active evidence to per-skill estimates |
| subskill engine | `src/adaptive/learner_model.py` (`lkm-subskill-v1`) | extends v2 to subskills and objectives; predictions |
| wrapper | `src/learner/knowledge_model.py` | facade over the skill engine: records evidence, materializes `skill_states`, history, explain |
| wrapper | `src/assessment/cefr_profile.py` | CEFR bands derived from the skill estimates |
| wrapper | `src/adaptive/snapshot.py` | gathers every engine input (evidence, vocabulary, catalog) into one `LearnerSnapshot` |
| **planner** | `src/adaptive/planner.py` (`adaptive-nba-v1`) | the only planner: pure function from a snapshot to ranked activities |
| wrapper | `src/adaptive/service.py` | builds the snapshot, plans, records the decision |

There is one planner. `/learner/plan` (what the UI shows), `/learner/insights`,
`/learner/recommendations` (the same plan with its full rationale) and
`polyglot plan` all call `src.adaptive.service.recommend`. The engine is the
one evaluated in `python -m evals.adaptive`; the curriculum planner it
replaced (`src/curriculum/`) was removed. Note that it plans only from the
evidence store and the language pack's catalog: grammar errors recorded only
in the analytics error table (writing-exercise corrections) do not reach it.

**Language packs** (`src/languages/`) — see
[`language-packs.md`](language-packs.md).

**Safety and security** (`src/safety/`, `src/security/`) — prompt-injection
hardening for scenario content, cultural-claim abstention, rate limiting,
token hashing/expiry, encrypted secrets, and the audit log. See
[`privacy.md`](privacy.md). Backups have one implementation, `src/ops/backup.py`
(verified backup sets); `polyglot security backup|backups` are aliases of
`polyglot ops backup|backups`.

**API** (`src/api/`) — a FastAPI app (`app.py`) exposing auth, chat/sessions,
review, progress, scenarios, profile, learner-model, trace, privacy, and cost
routes, every one of them scoped to the caller's own `user_id`.

**Frontends** — `src/main.py` + `frontend/gradio_app.py` (a Gradio MVP with
chat and voice), and `frontend/react_app/` (a Next.js dashboard that talks to
the FastAPI backend via `frontend/react_app/src/lib/api.ts`).

**Observability** (`src/observability/`) — `context.py` carries an
interaction id across `await` boundaries via `contextvars` so every model run
and evidence event in one turn can be correlated after the fact; `trace.py`
reconstructs a full turn from those records; `logging_config.py` configures
process-wide structured (JSON) or human-readable logging.

## Reliability

Two things can go wrong in a turn that must not crash it:

- **Every LLM provider is down or misbehaving.** `RoutingProvider` retries
  the same provider with exponential backoff, gives up on it and opens a
  circuit breaker after repeated failures (so a dead provider is skipped, not
  retried forever), fails over to the next provider in the chain, and — if
  the whole chain is exhausted — `conversation_node` degrades to a canned,
  in-character reply instead of propagating the exception. See
  `src/llm/reliability.py` and ADR [0026](adr/0026-production-reliability.md).
- **A secondary store fails during session finalization.** Analytics writes
  in `persist_session` are wrapped so a failure there cannot block marking
  the session `completed` or updating the learner's skill beliefs — the
  events that matter (evidence, vocabulary, grammar taxonomy) are already
  durable by the time analytics runs.

`GET /health` is a pure liveness probe. `GET /ready` (Phase 23) checks the
database, the LLM provider chain (config-only, no network calls), and the
vector store — see `src/api/app.py`'s `_readiness_checks`.

## Cost and latency

Every model call is recorded (`src/llm/telemetry.py`) with latency, tokens,
and an estimated USD cost; `src/llm/cost.py` aggregates those records per
session/user/turn via the existing observability link table (no new
storage). The evaluator only escalates to the costlier "primary" tier when a
grammar error is judged high-impact (`src.evaluation.policies.is_high_impact`)
— see [`evaluation.md`](evaluation.md). `conversation_node` caps how much
history it sends per turn (`MAX_HISTORY_MESSAGES`) instead of the full
transcript, and scenario YAML files are cached in memory keyed by
modification time.

## Testing

The whole suite runs offline: `tests/conftest.py` sets
`POLYGLOT_DETERMINISTIC=1` before any application module imports, which makes
`get_provider` resolve to a deterministic fake provider everywhere — no API
keys, no network, reproducible output. `make check` (lint + format-check +
typecheck + test) is the single local gate; CI runs the same targets.
