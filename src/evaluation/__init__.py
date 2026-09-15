"""Evaluation — the independent QA / verifier layer.

The Evaluator becomes a genuine safety-and-quality layer (Phase 9): for every
high-impact correction it can accept, revise, reject, or **abstain**. Abstention
is a feature — a tutor that says "I'm not confident this is wrong" is better
than one that confidently teaches incorrect language.

Modules:
- :mod:`policies`    — when to verify, and how confidence maps to a decision.
- :mod:`verifier`    — turn a candidate correction into a :class:`VerifierDecision`.
- :mod:`conflict`    — reconcile disagreements between agents (grammar vs culture).
- :mod:`calibration` — measure how well confidence matches observed correctness.
- :mod:`metrics`     — shared precision/recall/F1/MAE/correlation (Phase 18 evals).
"""

from src.evaluation.calibration import calibration_error, reliability_buckets
from src.evaluation.conflict import reconcile_grammar_culture
from src.evaluation.metrics import (
    PrecisionRecallResult,
    f1_score,
    false_positive_rate,
    mean_absolute_error,
    pearson_correlation,
    precision,
    recall,
)
from src.evaluation.policies import Decision, decide, is_high_impact
from src.evaluation.verifier import apply_decisions, verify_errors

__all__ = [
    "Decision",
    "PrecisionRecallResult",
    "apply_decisions",
    "calibration_error",
    "decide",
    "f1_score",
    "false_positive_rate",
    "is_high_impact",
    "mean_absolute_error",
    "pearson_correlation",
    "precision",
    "reconcile_grammar_culture",
    "recall",
    "reliability_buckets",
    "verify_errors",
]
