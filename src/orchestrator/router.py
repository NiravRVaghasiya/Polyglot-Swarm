"""Intent classification and mode routing.

Determines whether the user wants to:
- Continue/start a conversation
- Review vocabulary (SRS)
- End the session
"""

from typing import Any

from src.orchestrator.state import LearnerState


def router_node(state: LearnerState) -> dict[str, Any]:
    """Classify intent and decide which mode to enter.

    Routing logic:
    1. If should_end_session flag is set → end
    2. If there are pending reviews and turn_count == 0 → offer review
    3. Otherwise → conversation mode
    """
    if state.get("should_end_session"):
        return {"mode": "end"}

    # Check for pending FSRS reviews at session start
    pending = state.get("pending_reviews", [])
    if pending and state.get("turn_count", 0) == 0:
        return {"mode": "review"}

    return {"mode": "conversation"}


def route_by_mode(state: LearnerState) -> str:
    """Conditional edge function — routes based on current mode.

    Returns:
        Node name to route to: "conversation", "review", or "end"
    """
    mode = state.get("mode", "conversation")

    if mode == "end":
        return "end"
    elif mode == "review":
        return "review"
    else:
        return "conversation"
