"""Learner Knowledge Model — the persistent computational model of the learner.

This package is the strategic core of the product (Phase 6): a model of *what
the learner can and cannot do*, updated from evidence rather than from an LLM's
say-so. It sits between the evidence pipeline (what happened) and the curriculum
planner (what to do next).

Modules:
- :mod:`uncertainty`    — confidence/uncertainty helpers.
- :mod:`skill_graph`    — skill/construction prerequisite relations.
- :mod:`mastery_engine` — prior belief + new evidence -> posterior belief +
  uncertainty (a robust weighted-evidence model for MVP; the interface is
  designed so BKT/IRT/DKT can be swapped in later).
- :mod:`knowledge_model`— the top-level facade: read the current model, update
  it from a batch of events, and snapshot it.

The important part is the **interface**, not premature algorithmic complexity.
"""

from src.learner.knowledge_model import KnowledgeModel, get_knowledge_model
from src.learner.mastery_engine import MasteryEngine, SkillBelief

__all__ = ["KnowledgeModel", "MasteryEngine", "SkillBelief", "get_knowledge_model"]
