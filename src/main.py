"""Polyglot Swarm — Main entry point (Gradio MVP).

Run with: python -m src.main

This wires the LangGraph agent graph to a chat UI with real, persistent
sessions: state is seeded from the learner's profile, a single conversation
turn is run through the graph per message, and session outputs are persisted to
the memory layer when the session ends.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import gradio as gr

from src.config import settings
from src.orchestrator.graph import compile_graph
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.orchestrator.state import LearnerState
from src.scenarios.loader import Scenario, list_scenarios


def _available_scenarios() -> list[Scenario]:
    """Load the shipped scenarios for the UI dropdown (empty on failure)."""
    try:
        return list_scenarios()
    except Exception:  # noqa: BLE001 - UI should still load without scenarios
        return []

# Compile the LangGraph once (in-memory checkpointer is fine for the MVP UI;
# durable persistence happens via persist_session at session end).
app = compile_graph()


async def _run_turn(state: LearnerState, user_input: str) -> str:
    """Run a single conversation turn through the graph and return the reply.

    The graph loops (conversation -> analysis -> evaluator -> router), so we
    stream updates and stop once the conversation node has produced its reply
    for this turn, merging every node's state update back into ``state``.
    """
    state["last_user_input"] = user_input
    config = {
        "configurable": {"thread_id": state["session_id"]},
        "recursion_limit": 8,
    }

    reply = ""
    async for update in app.astream(state, config):
        for node_update in update.values():
            if not isinstance(node_update, dict):
                continue
            for key, value in node_update.items():
                if key == "messages":
                    state["messages"] = state.get("messages", []) + value
                else:
                    state[key] = value  # type: ignore[literal-required]
            if node_update.get("agent_response"):
                reply = node_update["agent_response"]
        # One conversation reply per user message is enough for the UI.
        if "conversation" in update:
            break

    return reply or "Lo siento, algo salió mal."


def chat(
    message: str,
    history: list[Any],
    language: str,
    scenario_id: str,
    session: dict[str, Any],
) -> str:
    """Gradio chat callback.

    ``session`` is a gr.State dict holding the persistent LearnerState between
    turns for this browser session.
    """
    state: LearnerState | None = session.get("state")
    if state is None:
        user_id = session.get("user_id") or f"web-{uuid.uuid4().hex[:8]}"
        session["user_id"] = user_id
        chosen = scenario_id or None
        state = build_initial_state(
            user_id,
            language if chosen is None else None,
            scenario_id=chosen,
        )
        session["state"] = state

    try:
        return asyncio.run(_run_turn(state, message))
    except Exception as e:  # noqa: BLE001 - surface errors to the UI
        return f"Error: {e}\n\nMake sure your API key is set in .env"


def end_session(session: dict[str, Any]) -> str:
    """Run end-of-session agents, persist outputs, and show the report."""
    state: LearnerState | None = session.get("state")
    if state is None:
        return "No active session."

    result = asyncio.run(finalize_session(state))
    session["state"] = None
    return str(result["report"])


def build_ui() -> gr.Blocks:
    """Build the Gradio chat interface."""
    with gr.Blocks(title="🌍 Polyglot Swarm", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🌍 Polyglot Swarm\n**Multi-agent AI language tutor**")

        session = gr.State({})

        scenario_choices = [("(free conversation)", "")] + [
            (f"{s.title} [{s.language}]", s.id) for s in _available_scenarios()
        ]

        with gr.Row():
            language = gr.Textbox(
                value=settings.default_language,
                label="Target Language",
                placeholder="Type any language: Spanish, Polish, Japanese, Swahili...",
                info="Used when no scenario is selected",
            )
            scenario = gr.Dropdown(
                choices=scenario_choices,
                value="",
                label="Scenario",
                info="Pick a scenario, or leave blank for free conversation",
            )

        gr.ChatInterface(
            fn=lambda msg, hist, lang, scen, sess: chat(msg, hist, lang, scen, sess),
            additional_inputs=[language, scenario, session],
        )

        with gr.Row():
            end_btn = gr.Button("End session & save")
            end_out = gr.Markdown()
            end_btn.click(fn=end_session, inputs=[session], outputs=[end_out])

    assert isinstance(demo, gr.Blocks)
    return demo


if __name__ == "__main__":
    # Launch the upgraded Gradio MVP (chat + voice + persistent sessions).
    from frontend.gradio_app import build_ui as build_voice_ui

    build_voice_ui().launch(server_port=settings.gradio_server_port)
