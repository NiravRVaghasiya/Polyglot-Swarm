# Learner model

This page describes how Polyglot Swarm turns "what happened in a session" into
a persistent belief about a learner for each skill. It also covers how the
CEFR level, the curriculum plan, and the audit trail are computed from that
belief. The design decisions are in [ADR-0031](adr/0031-evidence-driven-learner-knowledge-model.md),
which amends ADR-0006, ADR-0009, ADR-0010 and ADR-0015.

The model rests on three rules:

1. **Evidence is the source of truth.** Every belief is a deterministic
   projection of immutable evidence records. Replaying the same evidence
   always gives the same answer.
2. **Missing evidence is not weakness.** A skill with no graded evidence has
   no mastery value (`null`) and no CEFR band. A new learner has no level.
3. **Uncertainty is reported, not hidden.** Mastery, its interval, how much
   independent evidence backs it, and the quality of that evidence are
   separate fields. None of them is a calibrated probability.

## Evidence

A session's outputs go through the evidence pipeline (`src/evidence/`) before
anything else uses them:

```
raw session state
    │
    ▼
extractor.extract_from_state   — agent outputs → LearningEvent records
    │
    ▼
normalizer.normalize_all       — canonical construction ids / lemmas
    │
    ▼
deduplicator.deduplicate       — collapse repeats within one batch
    │
    ▼
store.record_events            — append-only `evidence` table (idempotent on event_id)
```

### What an evidence record carries

`LearningEvent` (`src/evidence/events.py`):

| Group | Fields |
|---|---|
| Competence | `skill` → `subskill` → `objective_id` → `item_id` (e.g. `grammar` → `ser_vs_estar` → `grammar.ser_vs_estar` → `ser_vs_estar`; `vocabulary` → `production` → `vocabulary.production` → `mesa`) |
| Outcome | `observed`, `expected`, `assessment`, `confidence` (how far the *evaluator's judgment* is trusted) |
| Task | `task_type` (`free_conversation`, `scenario_roleplay`, `review_recall`, …), `difficulty` in [0, 1] or `null`, `difficulty_basis` (`unknown`, `cefr_label`, `fsrs_card`, `measured`) |
| Provenance | `source`, `session_id`, `interaction_id`, `model_version`, `prompt_version` (e.g. `grammar@1`), `rubric_version` (e.g. `grammar-taxonomy-v1`), `created_at` (observation time), `recorded_at` (store time) |
| Independence | `correlation_id` (judgments of the same learner production share it), `fingerprint` (content hash; equal fingerprints mean duplicate evaluations) |
| Corrections | `supersedes` (the event a correction replaces), `schema_version` (1 for rows stored before ADR-0031; 3 since ADR-0034) |
| Modality (ADR-0034) | `modality` (`text` default, `audio`), `media_ref` (asset / submission / time span), `processing` (stages, providers, latencies), `transcription_confidence` (the recogniser's confidence, kept apart from `confidence`) |

For transcript-derived evidence the engine's reliability is
`confidence × transcription_confidence`: a poor recording counts for less
and is never read as low ability. A `scored` assessment carries a continuous
outcome in `payload.score` (e.g. a fluency score in [0, 1]). See
[multimodal-assessment.md](multimodal-assessment.md).

An unknown difficulty is `null` with basis `unknown`. It is never replaced by
a "medium" value. Difficulty sources today:

- **Grammar errors** take the construction's CEFR label from the language pack
  (`cefr_label`). A1 maps to 1/12, A2 to 3/12, and so on up to C2 at 11/12.
  This is a rating of the content, not a measured item difficulty.
- **Graded reviews** take the FSRS card's difficulty *before* the review
  (`fsrs_card`), with D in 1..10 mapped to (D−1)/9. A brand-new card has none.
- Nothing emits `measured` yet.

### Produced and exposed vocabulary

The vocabulary agent picks out words from the whole exchange, mostly from the
tutor's reply. A word counts as `VOCAB_PRODUCED` (weak positive evidence) only
when it appears in the learner's own text. Every other word is
`VOCAB_OBSERVED` with assessment `exposed`. Both kinds still join the lexicon
and the FSRS deck, but only produced words feed the production dimension.
Before ADR-0031 every such word counted as positive mastery evidence.

### Corrections never edit evidence

`store.supersede_event(event_id, replacement=..., reason=...)` appends a row
to `evidence_supersessions`, optionally with a replacement event. Called
without a replacement it is a retraction. The original row is never changed,
and `store.active_events()` leaves superseded rows out. Repeating the same
supersession has no effect.

## Mastery estimation (`lkm-evidence-v2`)

`src/learner/estimation.py`'s `EvidenceMasteryEngine` is a pure function from
a learner's active evidence to one `SkillEstimate` per skill. It does no I/O,
does not read the clock, and does not depend on input order. Every skill is
estimated from its own evidence only.

### Which evidence counts

| Kind | Examples | Effect |
|---|---|---|
| graded | `correct` (1.0), `incorrect` (0.0), `awkward` (0.35), `observed`/`produced` (0.75), acceptable variation such as `regional` or `informal` (0.6) | feeds mastery and coverage |
| exposure | `TURN_COMPLETED`, `VOCAB_OBSERVED`, `exposed`, `abstain` | coverage ("practised") only |
| ignored | unmappable assessments | listed in `explain`, otherwise unused |

### Independent observations

1. **Duplicates and correlated judgments merge into one observation.** The
   group key is `correlation_id` plus the item when a correlation id exists,
   and the fingerprint otherwise. A merged group averages its outcomes by
   reliability and keeps the *maximum* reliability, not the sum. Two agents
   flagging the same sentence for the same construction therefore count once.
2. **Repeats of the same item are discounted.** Within an item, observations
   are ranked newest first, and the k-th one has weight `0.5^k`. The total
   weight of an item is therefore at most twice that of a single observation,
   so drilling one word cannot stand in for breadth. The newest observation
   always has full weight.

### The model

The engine uses a Rasch-style logistic model. A graded observation `i` with
outcome `y_i` on a task of difficulty `d_i` succeeds with probability
`σ(θ − b_i)`, where `b_i = 4·(d_i − 0.5)` is the difficulty in logits.
Observations with unknown difficulty are placed at `b = 0` and discounted.
The ability `θ` is the weighted MAP estimate under a weak `Normal(0, 1.5²)`
prior. It is found by Newton–Raphson; the result is deterministic.

The weight of each observation is the product of:

| Factor | Value |
|---|---|
| reliability | the event's `confidence` |
| recency | `max(0.25, 0.5^(age / 60 days))`, with age measured from the newest evidence **for that skill**. Wall-clock time is not used, so replay is reproducible, and other skills' evidence is not used, so skills stay independent. |
| repetition | `0.5^k` (see above) |
| difficulty information | 1.0 when the difficulty is known, 0.8 when unknown |

The engine reports these values:

| Field | Meaning |
|---|---|
| `mastery` | `σ(θ̂)`: the model's success probability on a *reference* task of difficulty 0.5 (about the B1/B2 boundary). `null` without graded evidence. |
| `mastery_low` / `mastery_high` | `σ(θ̂ ± 1.96·SE)`, an approximate 95% interval *under the model's assumptions* |
| `uncertainty` | `SE / 1.5`: 1.0 means nothing is known beyond the prior |
| `evidence_index` (API: `confidence`) | `n_eff/(n_eff+6) × mean reliability × min(1, items/4)`. This is an **ordinal evidence-sufficiency score**, not a probability. |
| `confidence_label` | `none` / `low` / `medium` / `high`, from the status and interval width |
| quantity | `raw_count`, `graded_count`, `independent_count`, `effective_n`, `distinct_items`, `distinct_objectives`, `sessions` |
| quality | `mean_reliability`, `known_difficulty_share`, `redundancy_share` (merged duplicates), `exposure_share`, and an overall `score` |
| `baseline_mastery` | the pre-ADR-0031 `MasteryEngine` replayed over the same evidence, kept for comparison |
| `evidence_digest` | a hash of the method, the configuration and the skill's event ids |

Effect of difficulty: succeeding on hard tasks raises `θ` more than
succeeding on easy ones, and failing easy tasks lowers it more than failing
hard ones. Tests pin both properties.

### Evidence status

| Status | Rule (all thresholds are in `EngineConfig`) | CEFR band |
|---|---|---|
| `insufficient_evidence` | fewer than 3 independent observations, or fewer than 2 distinct items | none (`null`) |
| `provisional` | otherwise, when the rules for `estimated` are not all met | yes, flagged |
| `estimated` | at least 8 independent observations, at least 4 distinct items, at least 2 sessions, and an interval width of at most 0.4 | yes |
| `validated` | `estimated` plus at least 2 observations from a validated instrument (`task_type` of `standardized_test` or `expert_rating`) | yes |

No producer in the app emits validated-instrument evidence yet, so in practice
no skill reaches `validated`.

### Assumptions

These are working assumptions, not empirically fitted values:

- The prior SD (1.5 logits), the difficulty scale (±2 logits), the recency
  half-life (60 days) and floor (0.25), the repetition ratio (0.5), the
  unknown-difficulty discount (0.8) and the status thresholds are hand-chosen.
  They live in one `EngineConfig`.
- Graded assessments map to fixed outcome values, and fractional outcomes are
  used as a quasi-likelihood.
- Correlation is modelled only for the same production and the same item. Two
  different constructions flagged in one sentence count as two observations,
  although they share context.
- A CEFR-label difficulty rates the content, not how hard learners find it.
- The mastery-to-CEFR curve (below) is fixed. It has not been calibrated
  against expert ratings.

## Coverage

Each estimate carries a `SkillCoverage` that separates practice from
demonstrated competence:

| Field | Meaning |
|---|---|
| `practice_events`, `practiced_items` | anything seen, including exposure |
| `assessed_items`, `assessed_objectives`, `assessed_subskills` | distinct targets that have graded evidence |
| `demonstrated_items` / `_objectives` | targets whose weighted outcome is at least 0.7 |
| `struggling_items` / `_objectives` | targets whose weighted outcome is at most 0.35 |
| `catalog_size`, `catalog_assessed`, `catalog_demonstrated`, `unassessed_objectives` | for grammar, measured against the language pack's constructions; unassessed objectives are listed easiest first |

All coverage fields count distinct targets, so repeating an identical
exercise does not inflate them.

## Knowledge model, replay and history

`src/learner/knowledge_model.py`'s `KnowledgeModel`:

- `update_from_events(user, language, events)` records the events
  (idempotent on `event_id`) and then calls `recompute`. Bare
  `{skill, assessment, confidence}` dicts become `SKILL_EVIDENCE` events.
  Identical bare dicts share a fingerprint and therefore count once.
- `recompute(user, language)` replays the active evidence and compares the
  overall digest with the latest processing run. If nothing changed, it writes
  nothing, so processing is idempotent. Otherwise it materializes the changed
  skills into `skill_states` (a cache, with new columns from migration 0007)
  and appends one `lkm_processing_runs` row. That row stores the digest and
  the evidence and supersession high-water marks. It also appends one
  `mastery_updates` row per changed skill, with the mastery and status before
  and after, the baseline mastery, and the event ids added or removed since
  the previous run.
- `replay(user, language, run_id=None)` rebuilds the evidence set as of a past
  run from its high-water marks and recomputes it. It is pure, so a past
  estimate can be reproduced after later evidence or corrections.
- `explain(user, language, skill)` returns the estimate together with one
  `Contribution` per event: whether it was `counted`, `merged`, `exposure` or
  `ignored`, and its reliability, recency, repetition and difficulty factors
  and final weight.
- `current_estimates()` computes the estimates without writing anything.
  `current_beliefs()` and `mastery_by_skill()` still read the legacy
  `(mastery, uncertainty, sample_size)` view of `skill_states`.
- `snapshot()` writes the status, interval, counts and digest into
  `learner_state_snapshots` alongside the legacy fields.

The evidence order is stable: rows are sorted by observation time, then by
`event_id`. Importing the same evidence in a different order gives the same
estimates and digests; a test covers this.

## CEFR

`src/assessment/cefr_profile.py` (method `cefr-profile-v2`):

- Each skill's band is the fixed curve `<0.15 → A1`, `<0.35 → A2`,
  `<0.55 → B1`, `<0.75 → B2`, `<0.90 → C1`, otherwise C2, applied to its
  mastery. A band is given only when the status is `provisional` or better.
  The curve lives in `src/learner/cefr_bands.py`.
- **There is no default level.** A new learner gets `overall: null` with
  `overall_status: insufficient_evidence`. `default_profile()` no longer seeds
  `{"Spanish": "A2"}`, and `build_cefr_profile` no longer has a
  `fallback_cefr`.
- An overall band needs at least two skills at `provisional` or better. It is
  the minimum of their bands, and its status is the weakest of theirs.
  `overall_basis` lists those skills. `unassessed_skills` lists canonical
  skills with no usable evidence, and those are not counted as weak.
- `persist_profile()` writes rows to `assessments` with the new `status`
  column. `cefr` can be `NULL`.
- The legacy `confidence_from()` heuristic is kept only as the comparison
  baseline that the assessment eval scores. Its ECE is measured on a
  synthetic dataset and is not evidence of calibration on real learners.

### Working level and assessed level

The tutor still needs *some* level to pitch its language at. That is the
**working level** (`profile.cefr_by_language`, `state["cefr_level"]`), an
instructional setting:

- It is set by onboarding (self-report) or by the session heuristic in
  `src/agents/assessment.py`, and only when a session produced a signal.
- Before anything is recorded, prompts use
  `user_profile.DEFAULT_WORKING_LEVEL` ("A2"). That value is never stored,
  logged as an estimate, or shown as the learner's level.
- The session report shows both: `📈 Level estimate: <band or "not yet">
  (<status>) · tutor working level <level>`. The dashboard labels the
  session-log value "Working level".
- `finalize_session` now persists the CEFR profile *after* the session's
  evidence reaches the model. It used to persist it before, so the stored
  profile lagged one session behind.

## Curriculum

`src/curriculum/planner.py` gives every action an `intent`:

| Intent | When | Scoring |
|---|---|---|
| `assessment` | the skill is `insufficient_evidence`, or a grammar construction was flagged only once | `assessment_value`: information value from uncertainty, evidence quality and the coverage gap. No mastery input is used, so an unassessed skill is never scored as weak. |
| `remediation` | evidence at `provisional` or better with mastery < 0.4, or a grammar error that recurs at least twice | ELV with the estimate's mastery and uncertainty |
| `reinforcement` | 0.4 ≤ mastery < 0.75, and every FSRS-due review | ELV |
| `advancement` | mastery ≥ 0.75 and lower interval bound ≥ 0.5 | ELV |

Other planner rules:

- Readiness blocks a skill only when the evidence shows a prerequisite is weak
  (provisional or better, with mastery < 0.4). An unassessed prerequisite does
  not block.
- When grammar evidence is insufficient, a `diagnostic_check` targets the
  easiest grammar-pack construction that has not been assessed yet.
- At most `MAX_ASSESSMENT_ACTIONS` (2) assessments are planned while learning
  actions still fit. If time is left over, the deferred assessments fill it.
  No separate vocabulary probe is proposed when FSRS reviews are due, because
  a graded review already is vocabulary evidence.
- An unknown belief enters ELV as the neutral 0.5, never as 0.
- FSRS scheduling (`src/agents/srs.py`) is unchanged. The planner still takes
  *what is due* from `vocabulary_db.get_due`, most overdue first.

This planner still serves `/api/v1/learner/plan`. ADR-0033 adds an adaptive
engine alongside it, served at `/api/v1/learner/recommendations`. It adds:

- subskill (construction-level) estimates built on top of v2;
- predictions;
- adaptive difficulty;
- FSRS-integrated next-best activities;
- personalized learning paths.

See [adaptive-learning.md](adaptive-learning.md). The FSRS changes it makes
(new words get unreviewed cards; review modes) are described there.

## API surface

Routes under `/api/v1/learner` (`src/api/routes/learner_routes.py`) are
auth-scoped, call no LLM, and return typed responses (`src/api/schemas.py`):

| Route | Returns |
|---|---|
| `GET /plan` | ranked actions, each with `intent` |
| `GET /cefr` | the profile: `overall` (nullable), `overall_status`, `overall_basis`, `unassessed_skills`, and per skill `cefr` (nullable), `status`, `mastery` (nullable), `mastery_low`/`mastery_high`, `uncertainty`, `confidence` (evidence index), `confidence_label`, counts, `coverage`, `baseline_mastery` |
| `GET /skill-map` | the per-skill estimates, with evidence counts, quality and coverage |
| `GET /explain/{skill}` | one estimate plus its per-event contributions (404 if the skill has no evidence) |
| `GET /history?skill=` | every recorded mastery update, with its evidence ids |
| `GET /cefr-history` | the working-level time series from session logs |
| `GET /insights` | `overall_cefr` (nullable) and its status; `weakest_skills`, taken only from skills at provisional or better; `needs_assessment`; the top recommendations |

Consumers:

- The React types (`frontend/react_app/src/lib/api.ts`) make CEFR and mastery
  nullable. `TodaysPlan` shows "not yet assessed", the status, the mastery
  range, and each action's intent.
- The Gradio app has a "My level" panel.
- `polyglot assess` prints the status, the interval and the counts.
  `polyglot plan` prints each action's intent.
- `polyglot experiment measure` refuses to record an outcome when no overall
  level is supported. It used to record the default "A2".

## Persistence and migration

Migration 0007 (`src/memory/schema.py`) is additive and idempotent:

- **New columns on `evidence`:** `subskill`, `objective_id`, `task_type`,
  `difficulty`, `difficulty_basis` (default `unknown`), `model_version`,
  `rubric_version`, `prompt_version`, `correlation_id`, `supersedes`,
  `fingerprint`, `schema_version` (default 1), `recorded_at`.
- **New columns on `skill_states`:** `method`, `status`, `mastery_low`,
  `mastery_high`, `evidence_index`, `independent_n`, `effective_n`,
  `evidence_quality`, `baseline_mastery`, `coverage`, `last_evidence_at`,
  `evidence_digest`.
- **New column on `assessments`:** `status`.
- **New tables:** `evidence_supersessions`, `lkm_processing_runs` and
  `mastery_updates`, plus indexes.

Existing rows are not rewritten. A legacy evidence row reads back as schema
version 1 with an unknown difficulty, and its fingerprint is computed on read.
Legacy `skill_states` rows are replaced the next time that learner's model is
recomputed from its evidence. `tests/test_memory/test_migration_0007.py`
upgrades a real version-6 database to check all of this.

Privacy export now includes `evidence`, `evidence_supersessions` and the
learner-model history. Deletion removes the history too.

## Known limitations

- Only grammar errors, vocabulary production and exposure, and graded reviews
  produce graded evidence today. Speaking, listening, reading, writing and
  pragmatics have no producer, so they stay `insufficient_evidence` and the
  planner keeps proposing assessments for them.
- `GRAMMAR_SUCCESS` is never emitted, so grammar evidence is mostly negative.
  Grammar mastery is driven by errors and the prior, not by demonstrated
  correct use.
- The parameters and the mastery-to-CEFR curve are not calibrated against
  human ratings. `validated` cannot be reached until a validated instrument
  feeds evidence.
- Recomputing replays the full active evidence set for one learner and
  language. That is cheap at the current scale (a learner's evidence is
  hundreds to thousands of rows), but it is O(n) per update.
