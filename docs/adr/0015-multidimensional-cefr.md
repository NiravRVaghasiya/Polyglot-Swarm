# 0015. Multidimensional CEFR assessment (Phase 12)

- Status: Accepted
- Date: 2026-09-14

## Context

Assessment produced a single overall CEFR band per language (stored in the
profile). The plan wants CEFR treated as a multidimensional profile — a band
per skill, each with a confidence and a sample size — so progress reads like
"Speaking B1 ± ... (184 observations, medium confidence)" and can later be
validated against expert ratings.

## Decision

- Add `src/assessment/cefr_profile.py`: `build_cefr_profile` derives a per-skill
  band from the learner knowledge model's beliefs (mastery→band curve), with a
  confidence from the model's uncertainty and evidence volume, and an overall
  band that is the conservative minimum across skills. `persist_profile` writes
  one row per skill plus an overall row to the existing `assessments` store
  (tagged `method="cefr-profile-v1"`).
- Upgrade `assessment_node` to build and persist the profile *in addition to*
  its existing behavior: it still returns `{cefr_level}` and updates the
  profile's `cefr_by_language`, so every existing consumer and test is
  unaffected. Profiling runs best-effort (never breaks assessment).
- Add a `polyglot assess` CLI command to show the profile.

## Consequences

- The system now reports skill-specific proficiency with confidence and
  evidence, feeding the progress dashboard (Phase 16) and validation (Phase 12
  target: correlate with expert ratings).
- The deterministic overall-band estimate remains the single value the rest of
  the app reads; the profile enriches without replacing it.
- CEFR bands are derived from mastery via a fixed curve for now; the mapping and
  a validated calibration can be refined later without changing the interface.
