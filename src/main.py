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
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.orchestrator.state import LearnerState
from src.scenarios.loader import Scenario, list_scenarios


def _available_scenarios() -> list[Scenario]:
    """Load the shipped scenarios for the UI dropdown (empty on failure)."""
    try:
        return list_scenarios()
    except Exception:  # noqa: BLE001 - UI should still load without scenarios
        return []


async def _run_turn(state: LearnerState, user_input: str) -> str:
    """Run a single conversation turn and return the reply.

    Uses the API's turn runner, then waits for the turn's analysis agents and
    evaluator before returning: each Gradio call runs its own event loop, so
    a background analysis would not outlive it. This UI therefore records
    learning evidence like the API does, without the API's earlier reply.
    Durable persistence happens via persist_session at session end.
    """
    from src.api.sessions import run_turn, wait_for_analysis

    result = await run_turn(state, user_input)
    await wait_for_analysis(state)
    return result.reply if result.reply != "..." else "Lo siento, algo salió mal."


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


def gradio_auth(s: Any) -> tuple[str, str] | None:
    """Credentials for the Gradio UI (ADR-0035, R5).

    The UI has no accounts of its own and spends the operator's LLM budget,
    so staging/production refuse to start it without ``GRADIO_AUTH``
    (``user:password``).
    """
    user, sep, password = s.gradio_auth.partition(":")
    if sep and user and len(password) >= s.min_password_length:
        return (user, password)
    if s.is_production_like:
        raise SystemExit(
            "GRADIO_AUTH (user:password, password >= MIN_PASSWORD_LENGTH) is required "
            "to run the Gradio UI in staging/production."
        )
    return None


if __name__ == "__main__":
    from src.llm.preflight import check_backends, has_usable_backend

    # The UI still starts, but every reply would be a canned fallback, so say
    # why up front.
    checks = check_backends()
    if not has_usable_backend(checks):
        print("WARNING: no working LLM backend - replies will be canned fallbacks.")
        for check in checks:
            print(f"  {check.name}: {check.detail}" + (f" (fix: {check.fix})" if check.fix else ""))
        print("Run `polyglot health` for setup steps.")

    # Launch the upgraded Gradio MVP (chat + voice + persistent sessions).
    from frontend.gradio_app import build_ui as build_voice_ui

    build_voice_ui().launch(server_port=settings.gradio_server_port, auth=gradio_auth(settings))
