# 0001. Record architecture decisions

- Status: Accepted
- Date: 2026-09-14

## Context

Polyglot Swarm is moving from a prototype toward a production-grade adaptive
language-learning system, following a phased plan that spans learner modeling,
an evidence pipeline, provider abstraction, evaluation, and more. Decisions of
this scope need to be discoverable and durable: contributors join over time,
and the reasoning behind a structural choice is easily lost if it lives only in
a pull-request thread or someone's memory.

## Decision

We will record significant architecture decisions as Architecture Decision
Records (ADRs) stored in `docs/adr/`, using the lightweight format in
`template.md`. Each ADR is numbered sequentially, is immutable once accepted,
and is superseded (never edited) when a decision changes. ADRs are reviewed
through the normal pull-request process.

## Consequences

- New contributors can read the `docs/adr/` index to understand *why* the
  system is shaped the way it is, not just *how*.
- Adding an ADR is a small, explicit step in significant changes; this is minor
  overhead we accept in exchange for a durable decision log.
- The plan's Phase 24 ("open-source quality") calls for an ADR directory; this
  establishes it.
