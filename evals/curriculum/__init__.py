"""Curriculum evaluation suite.

Drives :func:`src.curriculum.plan_next_actions` — the Next Best Learning Action
planner — against seeded learner states in isolated storage (see
:func:`evals.harness.isolated_storage`) and checks the plan's shape against
what the plan (Phase 7/18) requires.

Plan (Phase 18) metrics and their status here:

- **target coverage** — measured: does a plan seeded with due reviews and
  grammar weaknesses actually surface actions targeting them?
- **skill balance** — measured: across a batch of learners with different weak
  skills, does the planner distribute actions across skills rather than
  fixating on one?
- **difficulty appropriateness** — measured: reuses
  :func:`src.curriculum.difficulty.difficulty_appropriate` directly against
  labeled (mastery, fatigue) cases — this is a pure function, so it is scored
  exactly rather than approximated.
- **learner success rate** — out of scope offline: it is an outcome measured
  from real usage over time (did following the plan improve the learner's
  mastery), not something a static seeded-state suite can produce.
"""
