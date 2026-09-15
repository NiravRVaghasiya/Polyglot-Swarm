"""Session and chat routes.

- POST /api/v1/sessions/start   — start a personalized session (optional scenario)
- GET  /api/v1/sessions/{id}/state — current session state
- POST /api/v1/sessions/{id}/end   — end session, run finalize, return report
- POST /api/v1/chat             — send a message, get reply + hidden feedback
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from src.api import sessions
from src.api.deps import get_current_user
from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    EndSessionResponse,
    HiddenFeedback,
    SessionStateResponse,
    StartSessionRequest,
    StartSessionResponse,
)
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.scenarios.loader import ScenarioError

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/sessions/start", response_model=StartSessionResponse)
def start_session(
    req: StartSessionRequest, user_id: str = Depends(get_current_user)
) -> StartSessionResponse:
    """Start a new learning session for the authenticated user."""
    try:
        state = build_initial_state(
            user_id,
            req.language if req.scenario_id is None else None,
            scenario_id=req.scenario_id,
        )
    except ScenarioError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    sessions.register_session(user_id, state)
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
    """End a session: run end-of-session agents, persist, and return the report."""
    state = sessions.get_session(user_id, session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await finalize_session(state)
    sessions.drop_session(user_id, session_id)
    return EndSessionResponse(report=result["report"], persisted=result["persisted"])


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user)) -> ChatResponse:
    """Send a message in an active session and get the reply + hidden feedback."""
    state = sessions.get_session(user_id, req.session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    reply = await sessions.run_turn(state, req.message)
    feedback = HiddenFeedback(
        grammar=[dict(e) for e in state.get("grammar_errors", [])],
        vocabulary=[dict(v) for v in state.get("new_vocabulary", [])],
        cultural=list(state.get("cultural_notes", [])),
    )
    return ChatResponse(reply=reply, hidden_feedback=feedback)
