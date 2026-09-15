# Architecture Decision Records

This directory records the significant architecture decisions for Polyglot
Swarm using lightweight [ADRs](https://adr.github.io/).

Each ADR is an immutable record of one decision: its context, the decision
itself, and its consequences. When a decision changes, we do not rewrite the
old ADR — we add a new one that supersedes it and mark the old one accordingly.

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-phase-0-tooling.md) | Phase 0 stabilization tooling choices | Accepted |
| [0003](0003-llm-provider-abstraction.md) | LLM provider abstraction with tiered routing | Accepted |
| [0004](0004-task-tier-routing-and-structured-output.md) | Task-tier routing, structured output, and telemetry (Phase 1) | Accepted |
| [0005](0005-sqlite-source-of-truth-and-migrations.md) | SQLite as source of truth, with a migration runner (Phase 2) | Accepted |
| [0006](0006-evidence-pipeline.md) | Evidence pipeline: what happened vs what we believe (Phase 3) | Accepted |
| [0007](0007-grammar-taxonomy-and-abstention.md) | Grammar taxonomy, classification, and abstention (Phase 4) | Accepted |
| [0008](0008-multidimensional-vocabulary.md) | Multi-dimensional vocabulary mastery and collocations (Phase 5) | Accepted |
| [0009](0009-learner-knowledge-model.md) | Learner Knowledge Model & mastery engine (Phase 6) | Accepted |
| [0010](0010-next-best-learning-action.md) | Next Best Learning Action / curriculum planner (Phase 7) | Accepted |
| [0011](0011-fsrs-contextual-review.md) | FSRS integration & contextual review with recall measurement (Phase 8) | Accepted |
| [0012](0012-verifier-and-abstention.md) | Evaluator as verifier: accept/revise/abstain + calibration (Phase 9) | Accepted |
| [0013](0013-language-packs.md) | Language packs (Phase 10) | Accepted |
| [0014](0014-transfer-graph.md) | Cross-language transfer graph with verification (Phase 11) | Accepted |
| [0015](0015-multidimensional-cefr.md) | Multidimensional CEFR assessment (Phase 12) | Accepted |
| [0016](0016-scenarios-as-pedagogical-environments.md) | Scenarios as pedagogical environments (Phase 13) | Accepted |
| [0017](0017-adaptive-difficulty-controller.md) | Multi-signal adaptive difficulty controller (Phase 14) | Accepted |
| [0018](0018-voice-vad.md) | Voice activity detection & pronunciation integration (Phase 15) | Accepted |
| [0019](0019-learner-model-api-and-frontend.md) | Learner-model API and frontend (Phase 16) | Accepted |
| [0020](0020-observability-and-tracing.md) | Observability: interaction correlation and turn tracing (Phase 17) | Accepted |
| [0021](0021-evaluation-harness.md) | Evaluation harness (Phase 18) | Accepted |
| [0022](0022-learning-science-experiment-platform.md) | Learning science experiment platform (Phase 19) | Accepted |
| [0023](0023-safety-and-correctness.md) | Safety and correctness (Phase 20) | Accepted |
| [0024](0024-security-and-privacy.md) | Security and privacy (Phase 21) | Accepted |
| [0025](0025-cost-and-latency-optimization.md) | Cost and latency optimization (Phase 22) | Accepted |
| [0026](0026-production-reliability.md) | Production reliability (Phase 23) | Accepted |
| [0027](0027-open-source-quality.md) | Open-source quality (Phase 24) | Accepted |
| [0028](0028-experiment-execution-and-published-results.md) | Experiment execution harness and published results (Gate C) | Accepted |
| [0029](0029-versioned-prompts.md) | Versioned prompt registry (Gate B) | Accepted |
| [0030](0030-frontend-voice-pwa-onboarding.md) | Frontend voice, PWA, and onboarding (Gate E) | Accepted |

## Creating a new ADR

1. Copy [`template.md`](template.md) to `NNNN-short-title.md` (next number).
2. Fill in Context, Decision, Consequences.
3. Add it to the index above.
4. Open a PR — ADRs are reviewed like code.
