# 0033. Adaptive learning intelligence

- Status: Accepted
- Date: 2026-11-07
- Amends: [0010](0010-next-best-learning-action.md) (next best action), [0031](0031-evidence-driven-learner-knowledge-model.md) (learner model)

## Context

After ADR-0031 the learner model was evidence-driven, but adaptation stayed
coarse.

- **Skill level only.** Mastery was estimated per *skill* (`lkm-evidence-v2`),
  so all grammar shared one number, and the planner could not tell a
  mastered construction from a weak one.
- **No predictions.** Nothing estimated the probability of success on a
  task, the risk of forgetting, or whether an objective was complete.
- **Fixed difficulty.** Every practice item was served at its content's
  CEFR level.
- **Short-term noise.** The model could not tell one bad session from a
  persistent weakness.
- **FSRS shortcomings.**
  - Meeting a word in conversation was recorded as a successful `Good`
    review.
  - Recognition and production were rated the same.
  - Repeated failures were re-drilled the same way.
  - `POST /api/v1/review/submit` bypassed FSRS altogether, so a word
    reviewed through the API stayed due forever.
- **Planner defects.**
  - Its value function was untested against outcomes.
  - It re-drilled flagged constructions at a fixed difficulty, including
    ones the learner had already mastered.
- **No data.** The app holds no real learner data: the evidence,
  vocabulary and session tables are empty. So no learning claim can be
  measured on real learners yet.

## Decision

1. **Subskill learner model `lkm-subskill-v1`** (`src/adaptive/learner_model.py`).
   It keeps v2 for skills and adds:
   - per-subskill offsets: an empirical-Bayes MAP with a `Normal(0, 1)`
     prior;
   - a faster recency decay for subskills;
   - a performance pattern: `temporary_dip`, `persistent_decline`,
     `persistent_weakness`, `improving`, `stable` or `single_session`;
   - success predictions with intervals, and the posterior probability that
     an objective is mastered.

   Every prediction is computed from evidence strictly before `as_of`
   (`evidence_before`).
2. **Model selection by held-out comparison.** BKT, Elo, the legacy
   incremental engine, v2 and v1 were compared on held-out simulated
   learners:
   - online prediction, predicting each attempt before observing it;
   - two ground-truth generators, `continuous` and `bkt`;
   - two data regimes: cold (no training data, as in the app today) and
     warm (parameters fitted on training learners).

   BKT and Elo live only in `evals/adaptive/candidates.py`. **No candidate
   wins everywhere.**
   - v1 beats the v2 baseline significantly in all four cells
     (AUC +0.02 to +0.13).
   - In the `continuous` world, Elo ties v1 on AUC but is slightly better
     calibrated (log loss −0.005, ECE −0.02).
   - In the `bkt` world, BKT is clearly best (AUC 0.87 vs 0.82–0.84).

   The app uses **v1, provisionally**: it is never worse than the baseline,
   it is difficulty-aware, and it is the only candidate that also gives:
   - uncertainty intervals (although these under-cover when the model is
     misspecified);
   - order-independent replay from evidence;
   - v2's evidence merging and audit trail.

   `python -m evals.adaptive models --logs <evidence.jsonl>` reruns the same
   comparison on real evidence. The choice must be revisited when real
   evidence exists. Full results are in `docs/adaptive-learning.md`.
3. **FSRS stays the scheduler, with corrected inputs.**
   - New words get unreviewed cards.
   - Reviews carry a mode: a recognition success is `Hard`, a production
     success keeps the learner's rating.
   - The API review route goes through `grade_review`.
   - `src/adaptive/memory.py` replays graded evidence through the same
     scheduler, for words and constructions. It never replays exposure. It
     counts correlated judgments once and flags leeches (three consecutive
     failures or four lapses).
4. **Adaptive difficulty** (`src/adaptive/difficulty.py`).
   - It targets ~75% predicted success, using a lower posterior quantile so
     that uncertainty makes tasks easier.
   - A temporary dip holds the difficulty; only persistent patterns lower
     it.
   - Steps are bounded at +0.08 and −0.12 per decision.
   - Task difficulty is kept separate from linguistic complexity: it may
     move at most ±0.15 around the content's CEFR difficulty.
5. **Next-best-activity engine `adaptive-nba-v1`** (`src/adaptive/planner.py`).
   - **Deterministic and LLM-free.**
   - **Candidates:** remediation, assessment, FSRS review, retention review,
     reinforcement, difficulty progression, new-concept introduction,
     vocabulary expansion and remediation, contextual conversation, and
     skill activities.
   - **Scoring:** each candidate gets ten named components in `[0, 1]`,
     combined with a per-intent weight table, a skill-balance factor and a
     fatigue factor.
   - **One recommendation per item:** when FSRS and the curriculum both
     want an item, the review wins and keeps both reasons.
   - **Limits:** at most two coverage assessments, and at most 40% of the
     session's time on them. A confirmation check after a one-session dip is
     exempt. At most one introduction per plan.
   - **Explanations:** every recommendation carries its activity, intent,
     objective, difficulty decision, prediction, rationale, expected
     benefit, evidence ids, uncertainty and score components.
6. **Personalized learning paths** (`src/adaptive/paths.py`).
   - Each objective's state, ordered prerequisites first.
   - Short-term and long-term horizons.
   - Prerequisite gaps, skill balance and recurrent errors.
   - Every change since the previous path, with the evidence counts behind
     it.
   - Activity preferences are explicitly not modelled: there is no evidence
     of them yet.
7. **Audit.** Migration 0008 adds `adaptive_decisions`, an append-only table.
   Served plans and paths are stored with their engine version and input
   digest, and are included in privacy export and deletion.
8. **API.** New endpoints under `/api/v1/learner`:
   - `recommendations`;
   - `path`;
   - `predictions`;
   - `decisions`.

   The existing `/plan` and its planner were unchanged at first; see
   *Single planner* below.
9. **Evaluation in simulation, labelled as such** (`evals/adaptive`).
   - **Learners:** a documented simulated-learner model.
   - **Policies compared:** a static syllabus, the existing planner (the
     real function, with its inputs pointed at the simulation) and three
     ablations of the new engine.
   - **Outcomes:** immediate and delayed outcomes are reported separately,
     as paired differences with bootstrap intervals.
   - **Robustness:** reruns with a flat learning-gain profile, a lower gain
     peak, and a BKT world.
   - **Labelling:** every report is marked SIMULATED.

## Consequences

- **The tutor can now:**
  - say *why* it recommends an activity, and with what confidence;
  - adapt difficulty per construction;
  - stop re-drilling mastered or failing material blindly.
- **API and FSRS changes:**
  - API reviews now reschedule cards, and new words are no longer counted
    as recalled.
  - Existing callers of `grade_review` keep the legacy behaviour unless
    they pass a mode.
- **Every effectiveness claim is a simulation result.** It depends on the
  simulator's assumptions, which are spelled out in
  `docs/adaptive-learning.md`. The robustness runs show which conclusions
  survive changes to them. Real learner studies are required before any
  claim about real learning gains.
- **Untuned parameters.** The value weights, target success, step bounds and
  leech thresholds are documented, explainable defaults. They were not tuned
  on real outcomes, and should be re-estimated once real evidence exists.
- **Single planner (2026-11-08).** The old curriculum planner was removed.
  `/plan` (what the UI shows), `/insights` and `polyglot plan` now use this
  engine through `src/adaptive/service.py`; `/plan` keeps its response shape
  and records each served plan, like `/recommendations`. The simulation's
  `existing_planner` policy went with it; paired differences are now taken
  against `static`. Results recorded before then (in
  `docs/adaptive-learning.md`) include the `existing_planner` column.
