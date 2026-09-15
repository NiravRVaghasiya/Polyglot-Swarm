"""Cost and latency aggregation, scoped to what actually incurred it.

``model_runs.cost_summary()`` (Phase 2) already gives a global, lifetime
total, but the plan (Phase 22) wants cost visible per conversation turn,
per session, per learning event, per review, and per assessment — i.e.
scoped to the unit of work that spent the money, not just a running total.

``model_runs`` has no ``session_id``/``user_id`` column (the telemetry write
path is deep in the LLM layer and knows nothing about sessions — see
:mod:`src.observability.links`), so every scoped view here is built the same
way the trace assembler (:mod:`src.observability.trace`, Phase 17) already
joins model runs to a session: via the ``session_interactions`` link table's
interaction ids. This module adds no new storage; it is a read-side
aggregation over what Phase 2/17/21 already persist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CostSummary:
    """Aggregated cost/latency/token totals over some set of model runs."""

    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    mean_latency_ms: float = 0.0
    failures: int = 0
    #: Per-tier breakdown, e.g. {"primary": {"calls": 3, "cost_usd": 0.01}, ...}
    #: — the natural grouping for "which tier is this session's money going
    #: to," since tiers are already the cost/quality lever (Phase 1 routing).
    by_tier: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 6),
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "failures": self.failures,
            "by_tier": self.by_tier,
        }


def _summarize(runs: list[dict[str, Any]]) -> CostSummary:
    """Reduce a list of ``model_runs`` rows into one :class:`CostSummary`."""
    if not runs:
        return CostSummary()

    by_tier: dict[str, dict[str, Any]] = {}
    for run in runs:
        tier = run.get("tier") or "unknown"
        bucket = by_tier.setdefault(tier, {"calls": 0, "tokens": 0, "cost_usd": 0.0, "failures": 0})
        bucket["calls"] += 1
        bucket["tokens"] += int(run.get("input_tokens") or 0) + int(run.get("output_tokens") or 0)
        bucket["cost_usd"] += float(run.get("cost_usd") or 0.0)
        if not run.get("success", 1):
            bucket["failures"] += 1

    for bucket in by_tier.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)

    total_tokens = sum(
        int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0) for r in runs
    )
    total_cost = sum(float(r.get("cost_usd") or 0.0) for r in runs)
    total_latency = sum(float(r.get("latency_ms") or 0.0) for r in runs)
    failures = sum(1 for r in runs if not r.get("success", 1))

    return CostSummary(
        calls=len(runs),
        tokens=total_tokens,
        cost_usd=total_cost,
        mean_latency_ms=total_latency / len(runs),
        failures=failures,
        by_tier=by_tier,
    )


def session_cost(session_id: str, user_id: str | None = None) -> CostSummary:
    """Aggregate cost/latency for every model run that ran under a session.

    Joins via :func:`src.observability.links.interactions_for_session`, the
    same bridge the trace assembler uses. Pass ``user_id`` when exposing this
    over an auth-scoped surface (an API route/CLI acting on behalf of a
    specific user) — without it, a caller could probe another user's session
    cost by guessing a session id, exactly the leak
    :func:`interactions_for_session` itself warns about.
    """
    from src.memory.model_runs import get_runs_by_interaction_ids
    from src.observability.links import interactions_for_session

    interaction_ids = interactions_for_session(session_id, user_id)
    runs = get_runs_by_interaction_ids(interaction_ids)
    return _summarize(runs)


def user_cost(user_id: str) -> CostSummary:
    """Aggregate cost/latency for every model run across a user's sessions."""
    from src.memory.model_runs import get_runs_by_interaction_ids
    from src.observability.links import interaction_ids_for_user

    interaction_ids = interaction_ids_for_user(user_id)
    runs = get_runs_by_interaction_ids(interaction_ids)
    return _summarize(runs)


def turn_cost(interaction_id: str) -> CostSummary:
    """Aggregate cost/latency for the model runs of a single turn.

    A "turn" is exactly one interaction (:mod:`src.observability.context`
    binds one interaction id per turn in :func:`src.api.sessions.run_turn`),
    so this is the finest-grained scope: what did *this one message* cost,
    across every agent's LLM call (conversation, grammar, vocabulary,
    cultural, evaluator) that ran while handling it.
    """
    from src.memory.model_runs import get_runs_by_interaction_ids

    return _summarize(get_runs_by_interaction_ids([interaction_id]))
