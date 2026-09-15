"""Polyglot Swarm benchmark harness.

Phase 0 provides the *harness*, not the full evaluation datasets (those arrive
with the Phase 18 evaluation suite). The goal here is a runnable, deterministic
`make benchmark` entry point from a clean checkout, so later phases have a place
to plug real component/end-to-end benchmarks into.

Run with::

    python -m benchmarks
    POLYGLOT_DETERMINISTIC=1 python -m benchmarks   # forces offline mode
"""
