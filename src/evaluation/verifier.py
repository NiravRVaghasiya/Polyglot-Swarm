"""The verifier — decide accept / revise / reject / abstain per correction.

Given the candidate grammar corrections and (optionally) the LLM's structured
per-error decisions, the verifier applies the policy in
:mod:`src.evaluation.policies` and returns the corrections to keep, which were
revised, and which were dropped (rejected or abstained). Abstention is
first-class: a low-confidence correction is suppressed rather than asserted.

This is pure logic (no LLM call) so it is deterministic and testable; the
evaluator agent supplies the LLM decisions and this module turns them into a
safe outcome that stays backward-compatible with the legacy ``overrides``
(index list) protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.evaluation import conflict
from src.evaluation.policies import Decision, decide


@dataclass
class VerificationOutcome:
    """The result of verifying a batch of candidate corrections."""

    kept: list[dict[str, Any]] = field(default_factory=list)
    #: Indices (into the original list) that were dropped (reject/abstain).
    dropped_indices: list[int] = field(default_factory=list)
    #: Per-index decision string for observability.
    decisions: dict[int, str] = field(default_factory=dict)
    #: Per-index confidence for calibration tracking.
    confidences: dict[int, float] = field(default_factory=dict)
    abstained: int = 0
    revised: int = 0


def _decision_for(
    index: int,
    error: dict[str, Any],
    llm_decision: dict[str, Any] | None,
) -> tuple[Decision, float, str | None]:
    """Resolve the decision, confidence, and revised text for one error.

    Uses the LLM's structured decision when provided; otherwise falls back to
    the error's own calibrated confidence (Phase 4) via the policy.
    """
    if llm_decision is not None:
        raw = str(llm_decision.get("decision", "accept")).lower()
        confidence = float(llm_decision.get("confidence", 1.0))
        revised = llm_decision.get("revised")
        try:
            return Decision(raw), confidence, revised
        except ValueError:
            # Unknown decision string -> fall back to policy on confidence.
            return decide(confidence, has_revision=bool(revised)), confidence, revised

    # No LLM decision: use the error's own confidence (default 1.0 = accept).
    confidence = float(error.get("confidence", 1.0))
    return decide(confidence), confidence, None


def verify_errors(
    grammar_errors: list[dict[str, Any]],
    *,
    cultural_notes: list[str] | None = None,
    llm_decisions: dict[int, dict[str, Any]] | None = None,
    override_indices: set[int] | None = None,
) -> VerificationOutcome:
    """Verify candidate corrections and return the safe outcome.

    Args:
        grammar_errors: the candidate corrections (post-grammar-agent).
        cultural_notes: notes used to reconcile register conflicts.
        llm_decisions: optional per-index :class:`VerifierDecision`-shaped dicts.
        override_indices: legacy explicit drop indices (backward compat).
    """
    cultural_notes = cultural_notes or []
    llm_decisions = llm_decisions or {}
    override_indices = override_indices or set()

    # Register conflicts (grammar vs culture) become forced drops.
    conflict_indices = {
        c["index"] for c in conflict.reconcile_grammar_culture(grammar_errors, cultural_notes)
    }

    outcome = VerificationOutcome()
    for i, error in enumerate(grammar_errors):
        # Legacy override or a culture conflict -> drop outright.
        if i in override_indices or i in conflict_indices:
            outcome.dropped_indices.append(i)
            outcome.decisions[i] = Decision.REJECT.value
            outcome.confidences[i] = 0.0
            continue

        decision, confidence, revised = _decision_for(i, error, llm_decisions.get(i))
        outcome.confidences[i] = confidence
        outcome.decisions[i] = decision.value

        if decision == Decision.REJECT:
            outcome.dropped_indices.append(i)
        elif decision == Decision.ABSTAIN:
            outcome.dropped_indices.append(i)
            outcome.abstained += 1
        elif decision == Decision.REVISE and revised:
            revised_error = dict(error)
            revised_error["correction"] = revised
            outcome.kept.append(revised_error)
            outcome.revised += 1
        else:  # ACCEPT (or REVISE without revised text)
            outcome.kept.append(error)

    return outcome


def apply_decisions(
    grammar_errors: list[dict[str, Any]],
    outcome: VerificationOutcome,
) -> list[dict[str, Any]]:
    """Return the kept corrections (already assembled on the outcome)."""
    return outcome.kept
