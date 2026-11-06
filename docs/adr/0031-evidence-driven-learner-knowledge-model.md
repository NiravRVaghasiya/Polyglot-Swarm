# 0031. Evidence-driven, difficulty- and uncertainty-aware learner knowledge model

- Status: Accepted (amends [ADR-0006](0006-evidence-pipeline.md), [ADR-0009](0009-learner-knowledge-model.md), [ADR-0010](0010-next-best-learning-action.md), [ADR-0015](0015-multidimensional-cefr.md))
- Date: 2026-11-06

## Context

An audit of the learner knowledge model (LKM) found the following defects:

- **Unsupported default levels.** `default_profile()` seeded
  `{"Spanish": "A2"}`. `build_cefr_profile(fallback_cefr="A2")` returned
  "A2" with zero evidence. `estimate_cefr` returned the default when there
  was no signal, and the session log then recorded it as an estimate.
  `polyglot experiment measure` recorded that default as a pre-test outcome.
- **Missing evidence read as zero.** Mastery started at 0.0, readiness
  treated a missing prerequisite as 0, and the planner used
  `.get(skill, 0.0)`.
- **No difficulty.** Success on an A1 task and success on a C1 task were the
  same evidence.
- **Confidence presented as calibrated.** The CEFR "confidence" was a
  heuristic over raw counts, and the evals reported an ECE for it.
- **Inflation from repeats.** N identical observations counted as N. Updates
  were incremental, so re-applying a session double-counted it. Words the
  vocabulary agent took from the *tutor's* reply counted as positive mastery
  evidence.
- **No coverage, weak provenance.** Breadth of assessed content was not
  represented. Evidence lacked objective, task, difficulty and
  prompt/rubric versions, and there was no correction mechanism or
  update history.
- **Thin evidence treated as weakness.** The planner had no notion of
  "assess first" and could recommend remediation for a skill it had barely
  observed.

## Decision

1. **Richer, immutable evidence.** `LearningEvent` gains `subskill`,
   `objective_id`, `task_type`, `difficulty` + `difficulty_basis` (unknown is
   distinct from measured), `prompt_version`, `rubric_version`,
   `correlation_id`, `supersedes`, a content `fingerprint` and a
   `schema_version`. Corrections are appended to `evidence_supersessions`;
   evidence rows are never updated. Vocabulary from the tutor's reply becomes
   `VOCAB_OBSERVED` (exposure). Grammar events take their difficulty from the
   language pack's CEFR label, and graded reviews from the FSRS card's prior
   difficulty.
2. **A pure evidence engine** (`src/learner/estimation.py`,
   `lkm-evidence-v2`). It fits a weighted MAP Rasch-style ability per skill,
   reports mastery as `σ(θ)` at a reference difficulty, and gives an interval
   and uncertainty from the Fisher information. Weights combine reliability,
   per-skill recency, a per-item repetition discount, and an unknown-difficulty
   discount. Duplicates and correlated judgments merge into one observation.
   Exposure evidence feeds coverage only. Each estimate carries its quantity,
   its quality, its coverage (practised, assessed, demonstrated, and coverage
   against the grammar-pack catalog), a status (`insufficient_evidence` →
   `provisional` → `estimated` → `validated`), and the old engine's value as
   `baseline_mastery`.
3. **The model is a projection.** `KnowledgeModel.recompute` replays the
   active evidence in a stable order. It materializes `skill_states` and
   appends `lkm_processing_runs` and `mastery_updates` only when the evidence
   digest changes, which makes processing idempotent. `replay(run_id)`
   reproduces any past run from its high-water marks, and `explain` lists each
   event's contribution.
4. **Nullable CEFR with states** (`cefr-profile-v2`). A band is given only at
   `provisional` or better. The overall band needs at least two such skills
   and is their minimum, and skills without evidence are listed as unassessed.
   The tutor's prompt pitch becomes an explicit **working level**, distinct
   from the assessed level: it is never seeded, and it is logged only when a
   session gives a signal.
5. **Intent-aware planning.** Every action is labelled `assessment`,
   `remediation`, `reinforcement` or `advancement`. Insufficient evidence
   leads to assessment, scored by information value rather than a guessed
   mastery. Assessments are capped while learning actions fit. A weak
   prerequisite blocks a skill only when the evidence demonstrates it.
   Grammar coverage drives diagnostics. FSRS scheduling is unchanged.
6. **Additive migration 0007**, updated API schemas (nullable fields, status,
   intent, plus `/explain/{skill}` and `/history`), and updated React, Gradio
   and CLI consumers. Privacy export and deletion include the new tables.

## Consequences

- Fewer numbers are shown, but each one is honest. A new learner sees "not
  yet assessed" and gets diagnostic suggestions.
- Every estimate can be traced to its evidence and reproduced. A retried
  `finalize_session` or `persist_session` no longer double-counts.
- **Tests that encoded the defects were updated rather than kept.** They had
  asserted the default "A2", N identical dicts as N observations, a hard A1
  after three errors (which now shrinks toward the prior), and the fixed
  `+0.333` ablation gain (now `+0.481`; the test checks its sign). The
  curriculum eval now seeds distinct items (dataset `2026.11.0`).
- The ablation metric still counts a skill without evidence as 0 *demonstrated*
  mastery. That is an outcome-measurement convention for comparing arms, and
  the payload now states which skills were unassessed.
- Remaining work, documented in `docs/learner-model.md`: there are no evidence
  producers for speaking, listening, reading, writing or pragmatics, and no
  `GRAMMAR_SUCCESS`. The parameters are uncalibrated, and `validated` cannot
  be reached until a validated instrument feeds evidence.
