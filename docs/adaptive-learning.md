# Adaptive learning

How Polyglot Swarm predicts learner performance, chooses the next activity
and its difficulty, coordinates spaced repetition, and builds a
personalized path. The design decision is
[ADR-0033](adr/0033-adaptive-learning-intelligence.md).

> **About the results on this page.** There is no real learner data in the
> system: the evidence, vocabulary and session tables are empty. Every
> effectiveness number here therefore comes from **simulated learners** and
> holds only under the simulator's assumptions, which are listed below. None
> of it is a real learning outcome. The harness can rerun the learner-model
> comparison on real evidence as soon as it exists (`--logs`, below).

## Components

| Module | What it does |
|---|---|
| `src/adaptive/learner_model.py` | `lkm-subskill-v1`: subskill (construction) estimates on top of `lkm-evidence-v2`, performance patterns, predictions, and the leakage guard |
| `src/adaptive/memory.py` | FSRS memory states replayed from demonstrated recall (words and constructions), and leeches |
| `src/adaptive/difficulty.py` | adaptive task difficulty |
| `src/adaptive/planner.py` | `adaptive-nba-v1` next-best-activity engine |
| `src/adaptive/paths.py` | personalized learning path |
| `src/adaptive/prediction.py` | prediction bundle served by the API |
| `src/adaptive/snapshot.py` | the single input value; built from the stores or from the simulator |
| `src/adaptive/audit.py` | append-only `adaptive_decisions` table (migration 0008) |
| `evals/adaptive/` | simulator, candidate models, model comparison, policy simulation |

API (authenticated, under `/api/v1/learner`):

- `GET /recommendations?language&minutes&goal&record` — the plan. It is
  recorded in the audit trail unless `record=false`.
- `GET /path?language&goal&target&record` — the learning path, with changes
  since the last recorded path.
- `GET /predictions?skill&subskill&difficulty&language` — predictions only,
  labelled `"kind": "prediction"`.
- `GET /decisions?language&kind&limit` — the audit trail.

`/plan` and the planner in `src/curriculum` are unchanged. They are kept for
compatibility and as the evaluation baseline.

## Learner model: `lkm-subskill-v1`

**Skill level.** This is exactly `lkm-evidence-v2`
([learner-model.md](learner-model.md)): a weighted MAP Rasch ability with
reliability, recency, repetition and difficulty weights, and merging of
duplicate and correlated judgments.

**Subskill offset.** For each subskill (each grammar construction), the model
fits an offset `delta` from the skill ability:

- the fit uses only that subskill's independent observations;
- the prior is `delta ~ Normal(0, 1)`;
- the skill ability is held fixed (two-stage empirical Bayes);
- evidence is decayed with a 21-day half-life, measured from the subskill's
  newest evidence.

The subskill ability is `theta + delta`, with
`SE = sqrt(SE_theta² + SE_delta²)`. A subskill with no evidence gets the skill
ability with the offset's full prior uncertainty, never a confident number.

**Predictions.**

- `P(success) = sigmoid(ability − b(d))` with `b(d) = 4(d − 0.5)`.
- The interval comes from ±1.96 SE.
- Objective completion is
  `P(success on the objective's own difficulty ≥ 0.8)` under the normal
  approximation to the posterior.
- Every prediction is built from evidence strictly before `as_of`
  (`evidence_before`). A prediction about the past never uses later evidence.
  A test checks this.

**Performance pattern.** The latest session is compared with the earlier
sessions:

1. Fit the earlier sessions.
2. Fit the latest session's *shift* from that fit, with the offset prior.
3. Classify the shift (z = 1.64):

| Pattern | Rule |
|---|---|
| `temporary_dip` | the last session is significantly below the earlier ones, and the session before it was not |
| `persistent_decline` | the last two sessions were each significantly below what came before |
| `persistent_weakness` | low mastery, with no dip or improvement |
| `improving` | the last session is significantly above |
| `single_session` | all evidence is from one session, so a dip and a weakness cannot be told apart |
| `stable` | none of the above |

## Adaptive difficulty

Two kinds of difficulty are kept apart:

- **Linguistic complexity** is the content's CEFR level. It is a fixed
  property of the construction.
- **Task difficulty** is how demanding the task is. It may move within ±0.15
  of the content's difficulty, which yields the `scaffolded`, `standard` and
  `stretch` tiers.

| Rule | Value |
|---|---|
| target predicted success | 0.75 (zone 0.65–0.85) |
| ability used | lower posterior quantile, `theta − 0.5·SE`: less evidence gives easier tasks |
| increase per decision | at most +0.08 |
| decrease per decision | at most −0.12, and only with a persistent pattern or when the success zone is left |
| `temporary_dip` | difficulty is held, never lowered |
| insufficient evidence | the content's own difficulty (a neutral probe) |

A property test checks the bounds for random inputs.

## Next-best activity: `adaptive-nba-v1`

The engine is deterministic and LLM-free. It runs in five steps.

1. **Estimate.** Compute the skill and subskill estimates and replay the
   retention states.
2. **Generate candidates:**
   - `diagnostic_check` (assessment): an objective with insufficient evidence,
     or a `temporary_dip` to confirm.
   - `grammar_practice`:
     - remediation for a demonstrated weakness (or a weak prerequisite);
     - reinforcement while in progress;
     - progression to a harder task once mastered;
     - introduction of the next construction whose prerequisites are
       mastered.
   - `retention_review`: a mastered construction whose FSRS retrievability is
     below 0.85.
   - `vocabulary_review` (FSRS-due): recognition first, production once
     recognition has been shown. A word met but never recalled is labelled
     so.
   - `vocabulary_remediation`: a leech (three consecutive failures or four
     lapses).
   - `vocabulary_expansion`: fewer than 8 words in learning.
   - `conversation_practice`: always available, for transfer.
   - Skill activities for listening, reading, writing and pragmatics.
3. **Score.** Each candidate gets ten components in `[0, 1]`, combined as a
   weighted mean (weights below), then multiplied by:
   - a skill-balance factor (±20% toward the goal's skill mix, from the last
     7 days of evidence);
   - the fatigue penalty.
4. **De-duplicate.** One recommendation per objective or item. When FSRS and
   the curriculum both want an item, the review wins and keeps both reasons.
5. **Select.** Greedy by score within the time budget:
   - at most 2 coverage assessments, taking at most 40% of the session's
     time;
   - dip confirmations are exempt from both limits;
   - at most 1 introduction;
   - ties break on (score, intent order, objective id).

Each component means:

| Component | Meaning |
|---|---|
| `gain` | expected learning gain: `(1 − P(mastery)) · zone(p)`, where `zone` peaks at the 0.75 target. Remediation uses `(1 − P(mastery)) · (0.5 + 0.5·zone(p))`, because re-teaching keeps value when even the easiest task is hard. |
| `success` | predicted success at the chosen difficulty |
| `retention` | forgetting risk, `1 − retrievability` |
| `importance` | goal skill weight × CEFR relevance to the target level |
| `relevance` | on the path's horizon: 1, or 0.4 beyond the target level |
| `uncertainty` | SE relative to the prior |
| `coverage` | never assessed, easier content first |
| `urgency` | overdue reviews, persistent patterns, dependent objectives |
| `difficulty_fit` | closeness of `p` to the target |
| `progression` | moves the learner forward |

Weights per intent:

| intent | gain | success | retention | importance | relevance | uncertainty | coverage | urgency | difficulty_fit | progression |
|---|---|---|---|---|---|---|---|---|---|---|
| review | 1 | 0.5 | 3 | 1 | 0.5 | 0 | 0 | 2 | 0.5 | 0 |
| remediation | 2 | 0.5 | 0 | 1 | 1 | 0 | 0 | 2.5 | 1 | 0 |
| assessment | 0.5 | 0 | 0 | 1 | 1 | 2.5 | 2 | 1.5 | 0 | 0 |
| reinforcement | 2.5 | 1 | 0.5 | 1 | 1 | 0.5 | 0 | 0.5 | 1.5 | 0 |
| progression | 1.5 | 1 | 0 | 1 | 1 | 0 | 0 | 0 | 1 | 2 |
| introduction | 2 | 0.5 | 0 | 1 | 1.5 | 0 | 0.5 | 0 | 0.5 | 2 |

These weights are explicit defaults. They have not been tuned on outcomes:
there are no real outcomes to tune them on.

**Each recommendation includes:**

- `activity`, `intent`, `skill`, `subskill`, `objective_id` and `target`;
- `mode` (for reviews);
- `difficulty`: the full decision, including the linguistic level, task tier,
  step and the bound that applied;
- `predicted_success`;
- `rationale`;
- `expected_benefit`;
- `evidence`: event ids and counts, retrievability, mastery probability;
- `uncertainty`;
- `components`, `score` and `sources`.

**Each plan includes:**

- the engine version and the snapshot's input digest;
- the configuration;
- the number of candidates considered;
- the deferred candidates, each with the reason it was deferred.

## FSRS integration

FSRS still decides *when* a word is due. The following changed.

- **New words are not counted as recalled.** `schedule_new_items` used to run
  one `Good` review when a word was merely met. New cards are now unreviewed
  (no stability, no `last_review`). They are due 10 minutes later, the same
  timing as before. Their first review is the first real retrieval.
- **Reviews carry a mode.** `grade_review(..., mode="recognition" | "production")`:
  - a recognition success is rated `Hard`;
  - a production success keeps the learner's rating;
  - a failure is `Again`.

  The mode is recorded as the evidence subskill and the mastery dimension.
  Without a mode, the legacy behaviour is unchanged.
- **The API review route uses FSRS.** `POST /api/v1/review/submit` now goes
  through `grade_review`. Before this, it only bumped a counter, so the word
  was never rescheduled and stayed due.
- **Read-only retention view.** `src/adaptive/memory.py` replays graded
  evidence through the same scheduler, for words and for constructions. It
  never replays exposure, it counts correlated judgments once, and it flags
  leeches. The planner uses this view for retention reviews, for leech
  remediation and for the recognition-to-production progression.
- **No duplicate recommendations.** De-duplication keeps one recommendation
  per item. A review absorbs any curriculum practice of the same item.

## Personalized path

`build_path` gives each catalog objective a state:

- `mastered`;
- `needs_review`;
- `in_progress`;
- `weak`;
- `blocked` (a weak prerequisite);
- `assess`;
- `not_started`.

Objectives are ordered prerequisites first, then by CEFR level, then by id.
The path then reports:

- **short term:** up to 4 objectives — weak, assess, review, in progress,
  then at most one new;
- **long term:** every objective up to the target level that is not
  mastered;
- **prerequisite gaps**;
- **skill balance:** recent share against the goal's target share;
- **recurrent errors:** objectives failed in two or more sessions;
- **changes:** each state change against the previously recorded path, with
  the evidence counts before and after.

Activity preferences are not modelled: there is no evidence about them yet.

## Evaluation (simulated)

```bash
python -m evals.adaptive models --family continuous   # or --family bkt
python -m evals.adaptive models --logs evidence.jsonl # REAL evidence, when it exists
python -m evals.adaptive policies --name policies-main [--gain-peak flat|0.5] [--family bkt]
```

Results are written to `evals/adaptive/results/`, as JSON plus a markdown
report. Every simulated report carries a "Simulated learners" banner.

### Simulator assumptions

The simulator is `evals/adaptive/simulator.py`.

- **World:** 12 grammar constructions (A1–B2, some with prerequisites), each
  with 6 items over three tiers, and 40 words, each with a recognition item
  and a production item.
- **Difficulty:** the app sees CEFR-label difficulty; true item difficulty
  adds hidden noise (SD 0.4 logits).
- **`continuous` learners:**
  - general ability and per-objective aptitude;
  - acquired knowledge, 40% permanent and 60% decaying with a stability that
    grows on successful spaced retrieval;
  - a per-session fluctuation (SD 0.4);
  - slip 0.05; guess 0.02 for production and 0.25 for recognition;
  - practice with feedback adds knowledge in proportion to a gain profile
    `h(p)`, which by default peaks at `p = 0.7` (desirable difficulty);
  - learning is slower while a prerequisite is unknown.
- **`bkt` learners:** discrete knowledge with learn, forget, slip and guess
  probabilities, and no difficulty effect.
- **Grading noise:** grades are flipped with probability
  `(1 − reliability)/2`. Conversation evidence has reliability 0.75 and is
  double-graded 25% of the time.
- **Common random numbers:** every policy faces the same learners and the
  same luck wherever their histories coincide.

### Learner-model comparison (Checkpoint 1)

**Protocol.**

- 40 training and 60 test simulated learners, each with 12 sessions of 10
  graded grammar attempts under a random practice policy.
- Online prediction of every test attempt before it is observed, giving
  7,200 predictions per cell.
- The target is the learner's *true* outcome, not the noisy grade.
- Two regimes:
  - **cold:** no training data, as in the app today;
  - **warm:** parameters fitted on the training learners.
- 95% intervals from a learner-level bootstrap.

**Cold regime** (the app today):

| model | AUC (continuous) | log loss (continuous) | AUC (bkt) | log loss (bkt) |
|---|---|---|---|---|
| legacy incremental | 0.694 [0.659, 0.721] | 0.660 | 0.663 [0.640, 0.686] | 0.722 |
| **lkm-evidence-v2 (baseline)** | 0.778 [0.757, 0.796] | 0.547 | 0.701 [0.681, 0.720] | 0.629 |
| BKT (literature defaults) | 0.784 [0.766, 0.799] | 0.549 | **0.868** [0.853, 0.879] | **0.432** |
| Elo | **0.802** [0.784, 0.819] | **0.518** | 0.822 [0.807, 0.833] | 0.512 |
| **lkm-subskill-v1** | **0.802** [0.783, 0.819] | 0.524 | 0.819 [0.804, 0.832] | 0.537 |

**v1 minus the baseline** (paired):

| world | AUC difference | log-loss difference |
|---|---|---|
| continuous | +0.024 [0.016, 0.034] | −0.023 [−0.031, −0.016] |
| bkt | +0.118 [0.104, 0.133] | −0.092 [−0.105, −0.080] |

**v1 minus Elo** (continuous world):

| measure | difference |
|---|---|
| AUC | −0.000 [−0.004, 0.003] |
| log loss | +0.005 [0.002, 0.009] |
| ECE | +0.019 [0.012, 0.024] |

So Elo is slightly better calibrated there.

**Warm regime:**

- BKT, fitted, reaches AUC 0.869 in the `bkt` world and 0.803 in the
  `continuous` world.
- Training-tuned v1 chose a 21-day half-life.
- Full tables: `evals/adaptive/results/models-*.md`.

**Uncertainty honesty.**

| world | v1 interval coverage (nominal 95%) |
|---|---|
| continuous | 0.90 |
| bkt, cold | 0.23 |
| bkt, warm | 0.43 |

The intervals are valid only when the model's logistic assumptions roughly
hold.

**Selection.**

- No model dominates.
- BKT wins when knowledge is discrete and difficulty does not matter.
- Elo and v1 tie on discrimination when it does matter.
- The app uses v1 **provisionally**:
  - it is never worse than the baseline in any cell;
  - it is difficulty-aware;
  - it is the only candidate with intervals, order-independent replay and
    the v2 audit trail.

The comparison must be rerun on real evidence (`--logs`) before the choice
is final.

### Planner outcomes (Checkpoint 6)

**Setup.**

- 40 simulated learners, 20 sessions of 20 minutes every 1–3 days.
- Delayed test 30 days after the last session, with no practice in between.
- Paired bootstrap 95% intervals.
- The world has only grammar and vocabulary, so every planner is told to
  avoid the other skills.

**Policies.**

| policy | what it is |
|---|---|
| `static` | fixed syllabus at the content level |
| `existing_planner` | the real current planner, with legacy FSRS |
| `adaptive` | new engine, all three capabilities off |
| `adaptive_predictive` | + subskill predictions and adaptive difficulty |
| `adaptive_full` | + FSRS integration |

**Main setting** (`continuous`, gain peak 0.7):

| metric | static | existing | adaptive | +predictive | +FSRS (full) |
|---|---|---|---|---|---|
| immediate success | 0.658 | 0.621 | **0.775** | 0.740 | 0.706 |
| grammar recall, delayed | 0.636 | 0.574 | 0.625 | **0.654** | 0.653 |
| objectives completed, delayed | 0.450 | 0.364 | 0.483 | 0.467 | 0.483 |
| grammar gain per hour | 0.192 | 0.110 | 0.172 | **0.251** | 0.249 |
| words introduced | 40.0 | 40.0 | 34.7 | 35.7 | 23.7 |
| per-word recall, delayed | 0.458 | 0.432 | 0.484 | 0.476 | **0.579** |
| words held ≥ 0.8 after 30 days | 4.5 | 4.3 | 5.0 | 5.0 | **6.0** |
| recommendation relevance (oracle) | 0.913 | 0.818 | **0.972** | 0.968 | 0.969 |

**Each capability's own effect** (paired, main setting):

| comparison | immediate success | delayed grammar recall | grammar gain / hour | per-word delayed recall | words held |
|---|---|---|---|---|---|
| adaptive − static | +0.117 [0.092, 0.142] | **−0.011** [−0.020, −0.003] | −0.020 [−0.038, −0.004] | +0.026 | +0.48 [0.23, 0.75] |
| + prediction & difficulty | −0.035 [−0.059, −0.011] | +0.029 [0.017, 0.042] | +0.079 [0.055, 0.104] | −0.008 | +0.03 (n.s.) |
| + FSRS integration (vs FSRS-only) | −0.034 [−0.050, −0.020] | −0.001 (n.s.) | −0.002 (n.s.) | +0.103 [0.089, 0.117] | +1.03 [0.65, 1.43] |
| full − static | +0.048 [0.026, 0.070] | +0.017 [0.007, 0.028] | +0.057 [0.039, 0.076] | +0.121 | +1.53 [1.05, 2.03] |

**Robustness:** delayed grammar recall, `adaptive_full` minus a baseline
(paired).

| setting | vs static | vs existing planner |
|---|---|---|
| main (`continuous`, gain peak 0.7) | **+0.017** [0.007, 0.028] | +0.079 [0.065, 0.093] |
| flat gain (difficulty does not matter) | −0.014 [−0.028, 0.000] | +0.069 [0.055, 0.085] |
| gain peak 0.5 | **−0.021** [−0.030, −0.012] | +0.036 [0.028, 0.045] |
| `bkt` world | **−0.106** [−0.135, −0.078] | **−0.050** [−0.081, −0.020] |

**Prediction accuracy inside the full policy** (main setting):

- Next-attempt predictions: n = 5,526, AUC 0.751, log loss 0.500, Brier
  0.161, ECE 0.090.
- FSRS retrievability against true delayed vocabulary recall: mean 0.71
  predicted vs 0.60 true. FSRS's default parameters over-predict this
  simulator's recall. Rank correlation 0.58 (0.03 in the `bkt` world).

### What the simulation supports, and what it does not

**Supported in all three `continuous` settings:**

- The **existing planner** is the weakest policy for delayed grammar
  recall. It re-drills flagged constructions at a fixed difficulty, often
  ones already mastered or still overwhelming (oracle relevance 0.82 vs
  0.97).
- **Prediction and adaptive difficulty** raise grammar learning per hour.
  The cost is a lower immediate success rate, which is the intended
  challenge.
- **FSRS integration** improves *per-word* delayed recall (+0.10 to +0.12).
  It does this by introducing fewer words and reviewing them more. The
  count of words held after 30 days rises significantly in the main and 0.5
  settings, but not in the flat-gain setting.

**Not supported robustly:**

- The adaptive engine beats a **static syllabus** on delayed grammar recall
  only under the desirable-difficulty assumption (gain peak 0.7). With flat
  or lower-peak gain, and in the `bkt` world, the static syllabus is as good
  or better.
- In the `bkt` world, the full engine is worse than both the static
  syllabus and the existing planner on grammar. It spends sessions on
  reviews, checks and conversation, while static simply covers more
  constructions. Grammar coverage, how quickly new constructions are
  introduced (at most one per plan), is the engine's main tuning target.

**Not measured at all:** real learning gains. These need real learner
studies.

## Limitations

- **No real learner data.** Every effectiveness and prediction number above
  is simulated. The simulator encodes the same desirable-difficulty idea the
  engine targets, which is why the robustness settings exist.
- **Negative-only grammar evidence.** The live app never emits
  `GRAMMAR_SUCCESS` ([learner-model.md](learner-model.md)). Construction-level
  estimates from conversation alone are therefore biased toward weakness
  until exercise or diagnostic producers emit both outcomes. The engine
  *recommends* `diagnostic_check` and `grammar_practice` activities, but no
  in-app exercise renderer exists yet that emits graded results for them.
- **Untuned parameters.** The value weights, the 0.75 target, the step
  bounds and the leech thresholds are untuned defaults.
- **Miscalibrated intervals.** The v1 intervals under-cover (0.90) even in
  the friendly world.
- **FSRS defaults.** FSRS uses default parameters. Per-user FSRS
  optimisation is not implemented.
- **Frontend not migrated.** The frontend still calls `/plan`; switching it
  to `/recommendations` is follow-up work.
