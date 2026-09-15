"""Task-oriented routing tiers.

The plan (Phase 1) wants routing by *task* rather than one-agent-one-provider.
It names four task tiers:

- ``critical_reasoning``  — hard conversation / difficult corrections
- ``fast_extraction``     — grammar/vocabulary extraction, latency-sensitive
- ``cheap_classification``— cheap yes/no or label decisions
- ``local_private``       — privacy mode, on-device

Rather than renaming the existing capability tiers (``primary``/``fast``/
``local``) — which flow through every agent and test — this module maps the
task tiers onto them. Callers may pass either a task tier or a capability tier
to :func:`src.llm.factory.get_provider`; both work.
"""

from __future__ import annotations

from src.llm.provider import Tier

#: Task tier -> capability tier.
TASK_TIER_MAP: dict[str, str] = {
    "critical_reasoning": "primary",
    "fast_extraction": "fast",
    "cheap_classification": "fast",
    "local_private": "local",
}

#: The capability tiers a chain can actually be built for.
CAPABILITY_TIERS: frozenset[str] = frozenset({"primary", "fast", "local"})


def resolve_tier(tier: Tier | str) -> str:
    """Resolve any tier name to a capability tier (primary/fast/local).

    Capability tiers pass through unchanged; task tiers are mapped. An unknown
    tier falls back to ``primary`` so a typo degrades to the safe default rather
    than raising.
    """
    if tier in CAPABILITY_TIERS:
        return str(tier)
    return TASK_TIER_MAP.get(str(tier), "primary")


def is_known_tier(tier: str) -> bool:
    """Whether ``tier`` is a recognized capability or task tier."""
    return tier in CAPABILITY_TIERS or tier in TASK_TIER_MAP
