"""Adaptive learning intelligence (ADR-0033): the app's only planner.

- :mod:`~src.adaptive.planner` — the pure next-best-activity engine
  (``adaptive-nba-v1``);
- :mod:`~src.adaptive.service` — builds a snapshot from the stores, plans and
  records the decision; every plan surface (API, CLI) calls it;
- :mod:`~src.adaptive.constraints` — the plan's time, goal and fatigue budget.
"""
