"""Learner Knowledge Model — the persistent computational model of the learner.

This package is the strategic core of the product (Phase 6): a model of *what
the learner can and cannot do*, updated from evidence rather than from an LLM's
say-so. It sits between the evidence pipeline (what happened) and the planner
(:mod:`src.adaptive.planner`, what to do next).

Modules:
- :mod:`uncertainty`    — confidence/uncertainty helpers.
- :mod:`estimation`     — the evidence-driven engine (ADR-0031): difficulty-
  aware, duplicate/correlation-aware ability estimates with uncertainty,
  evidence quality, coverage, and explicit evidence states.
- :mod:`mastery_engine` — the original incremental weighted-evidence rule,
  kept as the comparison baseline.
- :mod:`knowledge_model`— the top-level facade: read the current model, update
  it from a batch of events, and snapshot it.

The important part is the **interface**, not premature algorithmic complexity.
"""

from src.learner.estimation import (
    EvidenceMasteryEngine,
    EvidenceStatus,
    SkillEstimate,
)
from src.learner.knowledge_model import KnowledgeModel, get_knowledge_model
from src.learner.mastery_engine import MasteryEngine, SkillBelief

__all__ = [
    "EvidenceMasteryEngine",
    "EvidenceStatus",
    "KnowledgeModel",
    "MasteryEngine",
    "SkillBelief",
    "SkillEstimate",
    "get_knowledge_model",
]
