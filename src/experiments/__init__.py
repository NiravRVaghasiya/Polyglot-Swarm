"""Learning-science experiment execution (Phase 19 / Gate C).

The experiment *store* (:mod:`src.memory.experiments`) and the ablation *graph
builder* (:func:`src.orchestrator.graph.build_ablation_graph`) existed
separately, but nothing joined them into a runnable controlled comparison.
This package is that missing harness: it runs a scripted cohort of learners
through each ablation arm's graph, measures each learner's CEFR ordinal before
and after the intervention, records the outcomes to the store, and summarizes
the per-arm learning gain — turning "which architectural components create
learning value" from a design question into a measured one.

It runs fully offline in deterministic mode (``POLYGLOT_DETERMINISTIC=1``), so
the comparison is reproducible and requires no API keys or network.
"""

from src.experiments.runner import (
    ABLATION_EXPERIMENT,
    AblationReport,
    ArmResult,
    run_ablation_study,
    summarize_report,
)

__all__ = [
    "ABLATION_EXPERIMENT",
    "AblationReport",
    "ArmResult",
    "run_ablation_study",
    "summarize_report",
]
