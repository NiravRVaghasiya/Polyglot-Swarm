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
conversation_node  ──▶ persona-driven reply (LLM, "primary" tier)
    │
    ├──▶ grammar_node     (silent error detection, "fast" tier, JSON mode)
    ├──▶ vocabulary_node  (new-word extraction, "fast" tier, JSON mode)
    └──▶ cultural_node    (register/idiom notes, confidence-gated)
    │
    ▼
evaluator_node  ──▶ QA pass: accept/revise/abstain on grammar errors,
                    difficulty assessment, budget-aware tier escalation
    │
    ▼
router  ──▶ next turn, or a review/drill mode, or session end
```

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
`src/assessment/`) — see [`learner-model.md`](learner-model.md).

**Language packs** (`src/languages/`) — see
[`language-packs.md`](language-packs.md).

**Safety and security** (`src/safety/`, `src/security/`) — prompt-injection
hardening for scenario content, cultural-claim abstention, rate limiting,
token hashing/expiry, encrypted secrets, backups, and the audit log. See
[`privacy.md`](privacy.md).

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
