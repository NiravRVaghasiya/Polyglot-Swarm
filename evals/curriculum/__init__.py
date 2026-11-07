"""Curriculum evaluation suite.

Drives the planner — the adaptive next-best-activity engine, through
:func:`src.adaptive.service.recommend`, as the app does — against seeded
learner states in isolated storage (see :func:`evals.harness.isolated_storage`)
and checks the plan against what Phase 7/18 requires.

Metrics and their status here:

- **target coverage** — measured: does a plan seeded with due reviews and
  grammar weaknesses actually surface recommendations targeting them?
- **skill balance** — measured: across learners with different weak skills,
  does each learner's weak skill appear in their own plan?
- **difficulty appropriateness** — measured by the adaptive engine's own
  tests (``tests/test_adaptive``); the old planner's ``difficulty_appropriate``
  helper was removed with it.
- **learner success rate** — out of scope offline: it is an outcome measured
  from real usage over time, not something a static seeded-state suite can
  produce. ``python -m evals.adaptive`` simulates it.
"""
