# Learner model

How Polyglot Swarm turns "what happened in a session" into a persistent,
per-skill belief about a learner — and how the CEFR level shown in the UI is
actually computed.

## Evidence, not raw output

A session's outputs (grammar errors, vocabulary used, cultural notes, ...)
are not fed straight into the learner model. They go through an evidence
pipeline (`src/evidence/`) first:

```
raw session state
    │
    ▼
extractor.extract_from_state   — turn agent outputs into LearningEvent objects
    │
    ▼
normalizer.normalize_all       — consistent skill/assessment vocabulary
    │
    ▼
deduplicator.deduplicate       — collapse repeats within a session
    │
    ▼
store.record_events            — persisted, keyed by user/language/session
```

This separates "what happened" from "what we believe" — the belief layer
(mastery engine, below) is fed from deduplicated, normalized events rather
than directly from an LLM's raw JSON.

## Mastery engine

`src/learner/mastery_engine.py`'s `MasteryEngine` is deliberately **not** a
Bayesian network, IRT, or a trained model — it is a transparent, auditable
weighted-evidence rule, because a language tutor's learner model needs to be
explainable to the learner ("why does it think I'm at B1?"), not just
accurate.

Events are grouped by `skill`. Each event's `assessment` string maps to a
signal in `[0, 1]`:

| assessment | signal |
|---|---|
| correct | 1.0 |
| observed | 0.75 |
| regional / informal / formal / unusual / acceptable | 0.6 (mild positive — not an error) |
| abstain | 0.5 |
| awkward | 0.35 |
| incorrect | 0.0 |

The signal is weighted by the event's own `confidence` and blended into the
skill's running `mastery` via `src/learner/uncertainty.py`'s
`blend_weight(n, confidence)` — belief moves toward the new signal by a
shrinking amount as the effective sample size `n` grows, so one grammar
mistake doesn't swing an established belief but does move a fresh one.
`uncertainty_from_evidence(n)` shrinks the reported uncertainty the same way.

`KnowledgeModel.update_from_events(user_id, language, events)`
(`src/learner/knowledge_model.py`) runs this and writes the posteriors back
to the `skill_states` SQLite table (`src/memory/skill_state.py`'s
`upsert_skill`) — one row per `(user_id, language, skill)` with `mastery`,
`uncertainty`, `sample_size`, `updated_at`. `SKILLS` is an open, not strictly
enforced, canonical set: speaking, listening, reading, writing, grammar,
vocabulary, pragmatics.

`KnowledgeModel.snapshot(user_id, language, reason=...)` writes an immutable
JSON blob to `learner_state_snapshots` for longitudinal tracking — called at
session end (`reason="session_end"`) so mastery/uncertainty over time can be
plotted or rolled back to.

## CEFR estimation

`src/assessment/cefr_profile.py`'s `build_cefr_profile(user_id, language)`:

1. Reads `KnowledgeModel.current_beliefs()` for every skill.
2. Maps each skill's `mastery` to a CEFR band via a fixed, conservative
   curve: `<0.15 → A1`, `<0.35 → A2`, `<0.55 → B1`, `<0.75 → B2`,
   `<0.90 → C1`, else `C2`.
3. Computes a per-skill `confidence` from `1 - uncertainty` and a saturating
   function of `sample_size` — a band based on three data points is reported
   with lower confidence than the same band based on fifty.
4. The **overall** CEFR level is the *minimum* band across skills — a
   conservative aggregate, so a learner with excellent vocabulary but weak
   grammar is not shown a level their grammar doesn't support. A learner
   with no beliefs yet defaults to "A2".

`persist_profile()` writes one row per skill plus an overall row to the
`assessments` table with `method="cefr-profile-v1"`, so the method that
produced a historical estimate is always traceable.

## API surface

Every route under `/api/v1/learner` (`src/api/routes/learner_routes.py`) is
a thin, no-LLM wrapper over the stores above — safe to call synchronously
and frequently, unlike the chat routes:

| Route | What it returns |
|---|---|
| `GET /plan` | Next-best-action recommendations (`src.curriculum.plan_next_actions`) |
| `GET /cefr` | The full `build_cefr_profile` result |
| `GET /skill-map` | Raw per-skill beliefs (mastery/uncertainty/sample_size) |
| `GET /cefr-history` | A session-estimate time series (`src.memory.progress.cefr_progression`) |
| `GET /insights` | Progress overview + CEFR profile + top plan actions + weakest skills, composed into one explainable payload |

All routes are auth-scoped to the caller (`Depends(get_current_user)`) — a
learner can only ever see their own model.

`frontend/react_app/src/lib/api.ts` has typed wrappers (`plan()`,
`cefrProfile()`, `skillMap()`, `insights()`) that call exactly these
endpoints with the caller's bearer token.
