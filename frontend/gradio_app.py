"""Gradio MVP — chat + voice interface with persistent sessions.

Upgrades the basic chat UI with:
- Real, profile-seeded, persisted sessions (build_initial_state / finalize_session).
- Scenario selection.
- Optional voice: microphone input (Whisper STT) and spoken replies (Edge TTS),
  degrading gracefully to text-only when the voice extra is not installed.
- An end-of-session report showing every agent's contribution.
- A "My level" panel with the evidence-backed CEFR profile (nullable bands
  with their evidence status, ADR-0031).

Run: python -m frontend.gradio_app
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import gradio as gr

from src.api import sessions as session_manager
from src.config import settings
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.orchestrator.state import LearnerState
from src.scenarios.loader import Scenario, list_scenarios


def _available_scenarios() -> list[Scenario]:
    try:
        return list_scenarios()
    except Exception:  # noqa: BLE001 - UI must load even if scenarios fail
        return []


def _ensure_session(state_box: dict[str, Any], language: str, scenario_id: str) -> LearnerState:
    """Return the active LearnerState for this UI session, creating it if needed."""
    state: LearnerState | None = state_box.get("state")
    if state is None:
        user_id = state_box.get("user_id") or f"web-{uuid.uuid4().hex[:8]}"
        state_box["user_id"] = user_id
        chosen = scenario_id or None
        state = build_initial_state(
            user_id,
            language if chosen is None else None,
            scenario_id=chosen,
        )
        state_box["state"] = state
    return state


async def _turn(state: LearnerState, message: str) -> str:
    """One turn, analysis included: each call here runs its own event loop."""
    result = await session_manager.run_turn(state, message)
    await session_manager.wait_for_analysis(state)
    return result.reply


def chat_text(message: str, language: str, scenario_id: str, state_box: dict[str, Any]) -> str:
    """Handle a text message; returns the assistant reply."""
    state = _ensure_session(state_box, language, scenario_id)
    try:
        return asyncio.run(_turn(state, message))
    except Exception as e:  # noqa: BLE001 - surface errors to the UI
        return f"Error: {e}\n\nMake sure an LLM API key is set in .env"


def transcribe_audio(audio_path: str | None, language: str) -> str:
    """Transcribe mic audio to text (empty string if no audio or voice missing)."""
    if not audio_path:
        return ""
    try:
        from src.speech.stt import transcribe

        return transcribe(audio_path, language=language)
    except Exception as e:  # noqa: BLE001 - voice is optional
        return f"[voice unavailable: {e}]"


def synthesize_reply(text: str, language: str) -> bytes | None:
    """Synthesize the reply to speech (None if voice unavailable)."""
    if not text:
        return None
    try:
        from src.speech.tts import synthesize

        return asyncio.run(synthesize(text, language=language))
    except Exception:  # noqa: BLE001 - voice is optional, degrade to text-only
        return None


def end_session(state_box: dict[str, Any]) -> str:
    """Run end-of-session agents, persist, and return the report."""
    state: LearnerState | None = state_box.get("state")
    if state is None:
        return "No active session."
    result = asyncio.run(finalize_session(state))
    state_box["state"] = None
    return str(result["report"])


def learner_level_markdown(state_box: dict[str, Any], language: str) -> str:
    """Render the evidence-backed CEFR profile (ADR-0031) as Markdown.

    Bands are ``None`` until the evidence supports them, so this says
    "not yet assessed" rather than showing a default level.
    """
    from src.assessment import build_cefr_profile

    user_id = state_box.get("user_id")
    if not user_id:
        return "Start a conversation first — there is no evidence about you yet."
    profile = build_cefr_profile(user_id, language)
    overall = profile.overall or "not yet assessed"
    lines = [
        f"**Overall level:** {overall} — _{profile.overall_status.replace('_', ' ')}_",
        "",
        "| Skill | Level | Evidence | Mastery range |",
        "|---|---|---|---|",
    ]
    for skill, a in sorted(profile.skills.items()):
        span = (
            f"{a.mastery_low:.0%}–{a.mastery_high:.0%}"
            if a.mastery_low is not None and a.mastery_high is not None
            else "—"
        )
        lines.append(
            f"| {skill} | {a.cefr or '—'} | {a.status.replace('_', ' ')} "
            f"({a.independent_count} independent obs) | {span} |"
        )
    if profile.unassessed_skills:
        lines.append("")
        lines.append(f"_Not yet assessed:_ {', '.join(profile.unassessed_skills)}")
    lines.append("")
    lines.append("_Evidence labels describe how much the model has seen, not calibrated odds._")
    return "\n".join(lines)


def build_ui() -> gr.Blocks:
    """Build the Gradio Blocks app."""
    scenario_choices = [("(free conversation)", "")] + [
        (f"{s.title} [{s.language}]", s.id) for s in _available_scenarios()
    ]

    with gr.Blocks(title="🌍 Polyglot Swarm") as demo:
        gr.Markdown("# 🌍 Polyglot Swarm\n**Multi-agent AI language tutor** — chat or speak.")

        state_box = gr.State({})

        with gr.Row():
            language = gr.Textbox(
                value=settings.default_language,
                label="Target Language",
                info="Used when no scenario is selected",
            )
            scenario = gr.Dropdown(
                choices=scenario_choices,
                value="",
                label="Scenario",
                info="Pick a scenario, or leave blank for free conversation",
            )

        chatbot = gr.Chatbot(label="Conversation", height=380)

        with gr.Row():
            msg = gr.Textbox(label="Type your message", scale=4)
            mic = gr.Audio(sources=["microphone"], type="filepath", label="…or speak")

        with gr.Row():
            send_btn = gr.Button("Send", variant="primary")
            end_btn = gr.Button("End session & save")
            level_btn = gr.Button("My level")

        reply_audio = gr.Audio(label="Spoken reply", autoplay=True)
        report_out = gr.Markdown()
        level_out = gr.Markdown()

        def _on_send(
            message: str,
            mic_path: str | None,
            lang: str,
            scen: str,
            box: dict[str, Any],
            history: list[dict[str, str]] | None,
        ) -> tuple[list[dict[str, str]], bytes | None, str]:
            history = history or []
            text = message
            if not text and mic_path:
                text = transcribe_audio(mic_path, lang)
            if not text:
                return history, None, ""
            reply = chat_text(text, lang, scen, box)
            history = history + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": reply},
            ]
            audio = synthesize_reply(reply, lang)
            return history, audio, ""

        send_btn.click(
            _on_send,
            inputs=[msg, mic, language, scenario, state_box, chatbot],
            outputs=[chatbot, reply_audio, msg],
        )
        end_btn.click(end_session, inputs=[state_box], outputs=[report_out])
        level_btn.click(learner_level_markdown, inputs=[state_box, language], outputs=[level_out])

    assert isinstance(demo, gr.Blocks)
    return demo


if __name__ == "__main__":
    build_ui().launch(server_port=settings.gradio_server_port)
