"""Session and chat routes.

- POST /api/v1/sessions/start   — start a personalized session (optional scenario)
- GET  /api/v1/sessions/{id}/state — current session state
- POST /api/v1/sessions/{id}/end   — end session, run finalize, return report
- POST /api/v1/chat             — send a message, get the reply + hidden feedback
  for the turns analyzed so far (the turn itself is analyzed after the reply)

Database work runs in worker threads so it does not block the event loop.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from src.api import idempotency, sessions
from src.api.deps import get_current_user, rate_limited_user
from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    EndSessionResponse,
    HiddenFeedback,
    SessionStateResponse,
    StartSessionRequest,
    StartSessionResponse,
)
from src.llm.governance import BudgetExceededError
from src.orchestrator.lifecycle import build_initial_state
from src.scenarios.loader import ScenarioError

router = APIRouter(prefix="/api/v1", tags=["chat"])

#: Longest learner message accepted per turn; far beyond a conversational turn,
#: but stops one request from filling the model's context.
MAX_MESSAGE_CHARS = 2000


def budget_exceeded(exc: BudgetExceededError) -> HTTPException:
    """429 for a budget stop, telling the learner it is a limit, not a fault."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "budget_exceeded", "scope": exc.scope, "message": str(exc)},
    )


@router.post("/sessions/start", response_model=StartSessionResponse)
async def start_session(
    req: StartSessionRequest, user_id: str = Depends(rate_limited_user)
) -> StartSessionResponse:
    """Start a new learning session for the authenticated user."""
    await sessions.enforce_session_cap(user_id)
    try:
        state = await asyncio.to_thread(
            build_initial_state,
            user_id,
            req.language if req.scenario_id is None else None,
            scenario_id=req.scenario_id,
        )
    except ScenarioError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await asyncio.to_thread(sessions.register_session, user_id, state)
    scenario = state.get("current_scenario", {}) or {}
    return StartSessionResponse(
        session_id=state["session_id"],
        language=state["language"],
        cefr_level=state["cefr_level"],
        opening_line=scenario.get("opening_line", ""),
    )


@router.get("/sessions/{session_id}/state", response_model=SessionStateResponse)
def session_state(
    session_id: str, user_id: str = Depends(get_current_user)
) -> SessionStateResponse:
    """Return the current state of an active session."""
    state = sessions.get_session(user_id, session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return SessionStateResponse(
        session_id=session_id,
        language=state["language"],
        turn_count=state.get("turn_count", 0),
        cefr_level=state.get("cefr_level", "A2"),
    )


@router.post("/sessions/{session_id}/end", response_model=EndSessionResponse)
async def end_session(
    session_id: str, user_id: str = Depends(get_current_user)
) -> EndSessionResponse:
    """End a session: run end-of-session agents, persist, and return the report.

    Waits for the last turn's analysis, so the report includes it.
    Finalization happens once: a repeated or concurrent call gets 409.
    """
    state = await asyncio.to_thread(sessions.get_session, user_id, session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await sessions.finalize(user_id, session_id, state=state)
    if result is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ending")
    return EndSessionResponse(report=result["report"], persisted=result["persisted"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user_id: str = Depends(rate_limited_user),
    key: str | None = Depends(idempotency.idempotency_key),
) -> ChatResponse:
    """Send a message in an active session and get the reply + hidden feedback.

    The reply is returned as soon as the tutor has answered; the turn's
    grammar/vocabulary/cultural analysis runs afterwards, so ``hidden_feedback``
    covers the turns before this one (see :class:`HiddenFeedback`).
    With an ``Idempotency-Key`` header a retried message is not run twice.
    """
    if not req.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="message is empty")
    if len(req.message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"message is too long (max {MAX_MESSAGE_CHARS} characters)",
        )
    state = await asyncio.to_thread(sessions.get_session, user_id, req.session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    claim = await asyncio.to_thread(idempotency.begin, user_id, key, "chat", req.model_dump())
    if claim.replayed is not None:
        return ChatResponse.model_validate(claim.replayed)
    try:
        result = await sessions.run_turn(state, req.message)
    except BudgetExceededError as exc:
        await asyncio.to_thread(claim.abandon)
        raise budget_exceeded(exc) from exc
    except Exception:
        await asyncio.to_thread(claim.abandon)
        raise
    response = ChatResponse(
        reply=result.reply, hidden_feedback=HiddenFeedback.model_validate(result.feedback)
    )
    await asyncio.to_thread(claim.complete, response.model_dump())
    return response
