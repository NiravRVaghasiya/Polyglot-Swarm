# 0007. Grammar taxonomy, classification, and abstention (Phase 4)

- Status: Accepted
- Date: 2026-09-14

## Context

The grammar agent flagged every deviation as an error on a single severity
scale (minor/moderate/critical), with no notion of acceptable variation and no
calibrated confidence. That produces false corrections — the worst failure mode
for a tutor — when a learner uses valid regional, informal, or idiomatic
language. The plan (Phase 4) wants a structured taxonomy that distinguishes
wrong / awkward / unusual / regional / formal / informal / acceptable, calibrated
confidence, and a benchmark targeting high precision and a low false-correction
rate.

## Decision

- Extend `GrammarErrorModel` (and the `GrammarError` TypedDict, additively) with
  a `classification`, a `construction` id, `alternatives`, and `confidence`,
  while preserving the legacy five fields so downstream consumers (evidence
  extractor, session report) keep working.
- Rewrite `grammar_node` to request validated structured output
  (`generate_structured`) and only surface deviations classified as genuine
  errors (`wrong`/`awkward`) above a confidence threshold — otherwise it
  abstains. Tier (`fast`), determinism (`temperature=0.0`), and the short-input
  skip are preserved.
- Thread the classification into the evidence stream: a grammar event's
  `assessment` reflects the taxonomy instead of a hardcoded `"incorrect"`.
- Seed an explicit grammar taxonomy in language packs
  (`languages/{es,pl,it}/grammar/`) with a loader, and add a deterministic
  precision / false-correction benchmark.

## Consequences

- The tutor stops "correcting" valid variation; the false-correction rate is
  measurable and gated in the benchmark.
- The learner model receives richer, correctly-signed grammar evidence
  (acceptable variation is not a learner gap).
- Construction ids are grounded in versioned data, which the curriculum planner
  (Phase 7) and transfer graph (Phase 11) can reuse.
