# 0014. Cross-language transfer graph with verification (Phase 11)

- Status: Accepted
- Date: 2026-09-14

## Context

The transfer agent invented cognates and false friends purely from the LLM,
with no linguistic resource. The plan is explicit: don't rely only on embedding
similarity or LLM invention — retrieve candidates from a resource, then use the
LLM to verify. A confidently-invented false cognate is exactly the kind of
error the tutor must avoid.

## Decision

- Add `src/languages/transfer_graph.py`, which retrieves candidate transfer
  relations (cognates, false friends, interference) from
  `languages/<source>/transfer/<target>.yaml`.
- Rewrite `suggest_transfers` to retrieve candidates first; when candidates
  exist it uses a *verification* prompt (confirm/correct/drop) and prefers the
  LLM's verified output, falling back to the resource-backed relations when the
  LLM is unavailable. When no resource exists it degrades to the original
  open-ended prompt so unknown language pairs still work. The
  `transfer_suggestions` output shape and `transfer_node` are unchanged.
- Seed Spanish↔Italian (cognates + false friends) and Spanish→Polish
  (interference) resources.

## Consequences

- Transfer suggestions are grounded in curated linguistics; false cognates from
  pure invention are suppressed, and resource-backed relations work offline.
- The `TransferEdge` model + resource format give a clean place to grow the
  transfer graph (shared constructions, pronunciation carryover) per phase.
- A data error (a wrong `mesa→tavolo` "cognate") was caught and removed while
  wiring this up — evidence the resource-first approach surfaces mistakes.
