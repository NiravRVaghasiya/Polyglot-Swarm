"""Polyglot Swarm command-line interface.

Exposed as the ``polyglot`` console script. Provides:
- ``polyglot scenarios`` — list the available scenarios.
- ``polyglot chat`` — an interactive terminal conversation session, optionally
  driven by a scenario.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from src.orchestrator.graph import compile_graph
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.orchestrator.state import LearnerState
from src.scenarios.loader import ScenarioError, list_scenarios

app = typer.Typer(help="Polyglot Swarm — multi-agent language tutor.")
console = Console()


@app.command()
def scenarios(language: str | None = typer.Option(None, help="Filter by code (es/pl/it).")) -> None:
    """List available scenarios."""
    items = list_scenarios(language)
    table = Table(title="Available Scenarios")
    table.add_column("ID", style="cyan")
    table.add_column("Language")
    table.add_column("Title")
    table.add_column("Levels")
    for s in items:
        table.add_row(s.id, s.language, s.title, f"{s.cefr_min}–{s.cefr_max}")
    console.print(table)


async def _run_turn(app_graph: Any, state: LearnerState, user_input: str) -> str:
    """Run one conversation turn through the graph, returning the reply."""
    state["last_user_input"] = user_input
    config = {
        "configurable": {"thread_id": state["session_id"]},
        "recursion_limit": 8,
    }
    reply = ""
    async for update in app_graph.astream(state, config):
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
        if "conversation" in update:
            break
    return reply or "..."


@app.command()
def drill(
    language: str = typer.Option("Spanish", help="Target language name."),
    user: str = typer.Option("cli-user", help="User id."),
) -> None:
    """Generate targeted practice drills from your weaknesses and due words."""
    from src.agents.drills import generate_drills
    from src.memory.user_profile import load_profile

    profile = load_profile(user)
    items = asyncio.run(
        generate_drills(user, language, cefr_level=profile.cefr_for(language))
    )
    if not items:
        console.print("[dim]No drills yet — have a conversation session first.[/dim]")
        return
    for i, d in enumerate(items, 1):
        console.print(f"[cyan]{i}. ({d['type']}: {d['target']})[/cyan] {d['prompt']}")
        console.print(f"   [dim]answer: {d['answer']}"
                      + (f"  |  vs {d['confusable']}" if d.get("confusable") else "")
                      + "[/dim]")


@app.command()
def progress(
    language: str | None = typer.Option(None, help="Filter by language name."),
    user: str = typer.Option("cli-user", help="User id."),
) -> None:
    """Show a progress overview: streak, words learned, CEFR, top weaknesses."""
    from src.memory.progress import progress_overview

    ov = progress_overview(user, language)
    console.print(f"[bold green]Progress for {user}[/bold green]")
    console.print(f"  Sessions: {ov['total_sessions']}  |  Streak: {ov['current_streak']} day(s)")
    console.print(f"  Words learned: {ov['words_learned_total']}  |  CEFR: {ov['current_cefr']}")
    if ov["top_weaknesses"]:
        console.print("  Top weaknesses:")
        for w in ov["top_weaknesses"]:
            console.print(f"    • {w['error_type']} ({w['occurrences']}x)")


@app.command()
def peer(
    language: str = typer.Option("Spanish", help="Target language name."),
    topic: str = typer.Option("everyday small talk", help="Dialogue topic."),
    user: str = typer.Option("cli-user", help="User id."),
) -> None:
    """Generate a two-speaker dialogue to listen to, with a comprehension check."""
    from src.agents.peer import format_peer_dialogue, generate_peer_dialogue
    from src.memory.user_profile import load_profile

    profile = load_profile(user)
    result = asyncio.run(
        generate_peer_dialogue(language, cefr_level=profile.cefr_for(language), topic=topic)
    )
    console.print(format_peer_dialogue(result))


@app.command()
def write(
    text: str = typer.Argument(..., help="The text to get feedback on."),
    language: str = typer.Option("Spanish", help="Target language name."),
    user: str = typer.Option("cli-user", help="User id."),
) -> None:
    """Get detailed corrective feedback on a piece of writing."""
    from src.agents.writing import assess_writing, format_writing_feedback
    from src.memory.user_profile import load_profile

    profile = load_profile(user)
    result = asyncio.run(
        assess_writing(language, text, cefr_level=profile.cefr_for(language), user_id=user)
    )
    console.print(format_writing_feedback(result))


@app.command()
def ingest(
    text: str = typer.Argument(..., help="External target-language text to ingest."),
    language: str = typer.Option("Spanish", help="Target language name."),
    user: str = typer.Option("cli-user", help="User id."),
) -> None:
    """Simplify external content to your level and harvest vocabulary into review."""
    from src.agents.ingestion import ingest as ingest_content
    from src.memory.user_profile import load_profile

    profile = load_profile(user)
    result = asyncio.run(
        ingest_content(user, language, text, cefr_level=profile.cefr_for(language))
    )
    console.print("[bold]Simplified:[/bold]")
    console.print(result["simplified"] or "(nothing)")
    console.print(f"\n[dim]{result['stored']} word(s) added to your review queue.[/dim]")


@app.command()
def chat(
    language: str = typer.Option("Spanish", help="Target language name."),
    scenario: str | None = typer.Option(None, help="Scenario id (see `polyglot scenarios`)."),
    user: str = typer.Option("cli-user", help="User id for persistence."),
) -> None:
    """Start an interactive conversation session. Type 'quit' to end and save."""
    try:
        state = build_initial_state(
            user, language if scenario is None else None,
            scenario_id=scenario, session_id=f"cli-{uuid.uuid4().hex[:8]}",
        )
    except ScenarioError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    graph = compile_graph()

    scenario_ctx = state.get("current_scenario", {}) or {}
    persona = scenario_ctx.get("persona", {})
    console.print(
        f"[bold green]🌍 Polyglot Swarm[/bold green] — {state['language']} | "
        f"Level: {state['cefr_level']}"
    )
    opening = scenario_ctx.get("opening_line")
    if opening:
        console.print(f"[bold]{persona.get('name', 'Tutor')}:[/bold] {opening}")
    console.print("[dim](type 'quit' to end and see your report)[/dim]\n")

    while True:
        try:
            user_input = console.input("[cyan]You:[/cyan] ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.strip().lower() in {"quit", "exit"}:
            break
        reply = asyncio.run(_run_turn(graph, state, user_input))
        console.print(f"[bold]{persona.get('name', 'Tutor')}:[/bold] {reply}\n")

    console.print("\n[dim]Ending session...[/dim]")
    result = asyncio.run(finalize_session(state))
    console.print(result["report"])


if __name__ == "__main__":
    app()
