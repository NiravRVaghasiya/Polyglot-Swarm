# 0012. Evaluator as verifier: accept/revise/abstain + calibration (Phase 9)

- Status: Accepted
- Date: 2026-09-14

## Context

The evaluator dropped false-positive grammar corrections via a blunt index-based
override list, with no confidence and no notion of abstention. The plan wants a
genuine safety/quality layer: for every high-impact correction, accept / revise
/ reject / **abstain**, with calibrated confidence — because a tutor that says
"I'm not confident this is wrong" is better than one that confidently teaches
incorrect language.

## Decision

Add `src/evaluation/`:

- `policies.py` — high-impact detection and the confidence→decision thresholds
  (accept ≥ 0.75; abstain < 0.5).
- `verifier.py` — per-correction decisions; uses the LLM's structured decision
  when available, else the correction's own calibrated confidence (Phase 4);
  legacy override indices and grammar-vs-cultural conflicts become forced drops;
  `revise` swaps in a better correction.
- `conflict.py` — reconciles register conflicts (grammar flags a form the
  cultural context endorses).
- `calibration.py` — Expected Calibration Error + reliability buckets, exercised
  by a deterministic calibration benchmark.

`evaluator_node` routes corrections through the verifier while preserving its
existing return contract (`{evaluation, grammar_errors}`, the `overrides` /
`grammar_errors_overridden` / `difficulty_assessment` keys, the no-LLM fast
path, and failure degradation); verifier detail is added under a new
`verifier` key.

## Consequences

- False corrections are actively suppressed (abstention), and every decision is
  observable and confidence-tagged.
- Calibration is measurable, feeding the evaluation harness (Phase 18).
- The change is additive: the legacy override protocol and all existing
  evaluator tests keep working.
