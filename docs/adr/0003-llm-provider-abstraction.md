# 0003. LLM provider abstraction with tiered routing

- Status: Accepted
- Date: 2026-09-14

## Context

The system uses multiple LLM backends (Claude for quality, Gemini for fast/cheap
extraction, Ollama for local/private inference) and must degrade gracefully when
one is unavailable. If agents called vendor SDKs directly, they would be coupled
to specific providers, hard to test offline, and unable to fail over. The 10/10
plan (Phase 1) explicitly requires that "no agent imports a vendor SDK directly"
and that provider failure triggers controlled fallback.

## Decision

We will keep all model access behind a single `LLMProvider` interface
(`src/llm/provider.py`). Agents request a *tier* — `primary`, `fast`, or
`local` — via `get_provider(tier)`; the factory returns a `RoutingProvider`
that prefers the tier's provider and fails over, in a defined order, to any
other *available* provider. Concrete providers import their SDKs lazily so a
deployment only needs the packages for the backends it uses. Deterministic mode
(ADR-0002) plugs a `FakeProvider` into this same seam.

## Consequences

- Agents remain vendor-agnostic and testable offline; adding a new provider is a
  new `LLMProvider` implementation plus a builder entry, no agent changes.
- Failover is centralized and observable (logged) rather than scattered.
- Routing is currently a static preference-plus-fallback order. The plan's later
  budget-aware / task-tier routing (Phase 22) can extend `RoutingProvider`
  without changing the agent-facing `get_provider` contract.
