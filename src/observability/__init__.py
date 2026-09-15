"""Observability — correlate and reconstruct what the tutor did.

The plan (Phase 17) wants any bad tutor response to be reconstructable
end-to-end: user input → retrieved memory → prompt → model output → grammar
analysis → evaluator decision → learner-state update → curriculum decision.

The signals already exist as separate records — LLM calls (``model_runs``) and
structured evidence events (``evidence``) — but they were not correlated. This
package adds:

- :mod:`context` — a contextvar carrying the current interaction id, so every
  LLM call made while handling a turn is stamped with it (no plumbing through
  every function signature).
- :mod:`trace` — a trace assembler that stitches the model runs and evidence
  events for an interaction/session back into an ordered, readable trace.
"""

from src.observability.context import (
    current_interaction,
    current_session,
    interaction_scope,
    new_interaction_id,
)
from src.observability.trace import (
    Span,
    Trace,
    assemble_trace,
    format_trace,
)

__all__ = [
    "Span",
    "Trace",
    "assemble_trace",
    "current_interaction",
    "current_session",
    "format_trace",
    "interaction_scope",
    "new_interaction_id",
]
