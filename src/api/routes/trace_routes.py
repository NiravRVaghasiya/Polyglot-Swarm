"""Observability route: reconstruct a session's turn trace (Phase 17).

Exposes the trace assembler over the API so a bad tutor response can be
inspected end-to-end: the LLM calls it made and the structured evidence it
produced, correlated by interaction id and ordered in time. Auth-scoped to the
requesting user, so one learner can only trace their own sessions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import TraceResponse

router = APIRouter(prefix="/api/v1/trace", tags=["observability"])


@router.get("/{session_id}", response_model=TraceResponse)
def get_trace(
    session_id: str,
    language: str | None = None,
    user_id: str = Depends(get_current_user),
) -> TraceResponse:
    """Return the reconstructed trace (model runs + evidence) for a session."""
    from src.observability.trace import assemble_trace

    trace = assemble_trace(user_id, session_id, language=language)
    return TraceResponse.model_validate(trace.as_dict())
