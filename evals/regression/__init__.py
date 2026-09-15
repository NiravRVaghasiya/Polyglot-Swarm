"""Regression suite: one gate over every capability suite.

The plan (Phase 18) wants "every model/prompt change runs evaluation" — a
single command that answers "did anything regress?" without having to remember
which individual suites exist. This suite re-runs grammar, vocabulary, and
assessment (the suites with a numeric pass/fail bar) and reports one rolled-up
result, so CI/a pre-merge check can gate on it alone if it wants a single
signal instead of the full breakdown.

Curriculum is intentionally excluded from the rollup: it mutates SQLite state
via :func:`evals.harness.isolated_storage`, which is heavier and better kept as
its own explicit suite than folded into a lightweight regression gate.
"""
