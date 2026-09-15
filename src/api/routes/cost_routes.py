"""Cost/latency visibility routes (Phase 22).

Auth-scoped to the requesting user, the same way trace_routes is: a session's
cost is only ever computed for the caller's own sessions, since model_runs
carries no user column of its own and is joined in purely via the
observability link table (see src.llm.cost / src.observability.links).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import CostSummaryResponse

router = APIRouter(prefix="/api/v1/cost", tags=["observability"])


@router.get("/session/{session_id}", response_model=CostSummaryResponse)
def get_session_cost(
    session_id: str,
    user_id: str = Depends(get_current_user),
) -> CostSummaryResponse:
    """Return LLM cost/latency for one of the caller's own sessions."""
    from src.llm.cost import session_cost

    summary = session_cost(session_id, user_id)
    return CostSummaryResponse.model_validate(summary.as_dict())


@router.get("/me", response_model=CostSummaryResponse)
def get_my_cost(user_id: str = Depends(get_current_user)) -> CostSummaryResponse:
    """Return LLM cost/latency across all of the caller's own sessions."""
    from src.llm.cost import user_cost

    summary = user_cost(user_id)
    return CostSummaryResponse.model_validate(summary.as_dict())
