"""Polyglot Swarm command-line interface.

Exposed as the ``polyglot`` console script. Provides:
- ``polyglot scenarios`` — list the available scenarios.
- ``polyglot chat`` — an interactive terminal conversation session, optionally
  driven by a scenario.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from src.observability.logging_config import ensure_configured
from src.orchestrator.graph import compile_graph
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.orchestrator.state import LearnerState
from src.scenarios.loader import ScenarioError, list_scenarios

# Phase 23: configure logging once, at process start, before any command runs
# — so every polyglot.* logger actually produces visible output (level/format
# controlled by settings.log_level/log_format) rather than being silently
# dropped by Python's logging "handler of last resort".
ensure_configured()

app = typer.Typer(help="Polyglot Swarm — multi-agent language tutor.")
console = Console()

#: Learning-science experiment commands (Phase 19), grouped under `polyglot
#: experiment ...` since they're a distinct concern from the day-to-day
#: learner-facing commands above.
experiment_app = typer.Typer(help="Controlled comparisons: create, assign, measure, report.")
app.add_typer(experiment_app, name="experiment")

#: Security/privacy operations (Phase 21): backups and the audit log. Grouped
#: separately from the learner-facing commands since these are
#: operator/admin actions, not something a learner runs day to day.
security_app = typer.Typer(help="Backups and the security audit log.")
app.add_typer(security_app, name="security")

#: Self-service data export/deletion (Phase 21) — a learner's own right to
#: see or erase their data, distinct from `security` (operator actions).
privacy_app = typer.Typer(help="Export or delete a user's own data.")
app.add_typer(privacy_app, name="privacy")

#: Cost/latency visibility (Phase 22) — scoped to a session/user rather than
#: only the lifetime global total `model_runs.cost_summary()` gives.
cost_app = typer.Typer(help="LLM cost and latency, scoped to a session or user.")
app.add_typer(cost_app, name="cost")


@app.command()
def results(
    stdout: bool = typer.Option(
        False, "--stdout", help="Print the artifact instead of writing docs/results.md."
    ),
    learners: int = typer.Option(3, help="Synthetic learners per ablation arm."),
) -> None:
    """Generate the measured-results artifact (docs/results.md).

    Runs the benchmark harness, the evaluation suites, and the ablation study
    deterministically and writes their actual numbers to docs/results.md, with
    a known-limitations section. Requires deterministic mode
    (POLYGLOT_DETERMINISTIC=1) so the artifact is reproducible offline.
    """
    import os

    from src.experiments.results import DEFAULT_OUTPUT, generate

    if not os.getenv("POLYGLOT_DETERMINISTIC"):
        console.print(
            "[red]Results generation requires deterministic mode.[/red] "
            "Set POLYGLOT_DETERMINISTIC=1 and re-run."
        )
        raise typer.Exit(code=1)

    markdown = asyncio.run(generate(learners_per_arm=learners, write=not stdout))
    if stdout:
        console.print(markdown, markup=False)
    else:
        console.print(f"[bold green]Wrote[/bold green] {DEFAULT_OUTPUT}")


@app.command()
def health() -> None:
    """Report version, configuration, and LLM provider health.

    Exits non-zero if configuration is invalid (e.g. no LLM backend), so it is
    usable as a readiness check in scripts and CI.
    """
    from src import __version__
    from src.config import settings, validate_settings
    from src.llm.factory import get_provider
    from src.llm.provider import Tier

    console.print(f"[bold green]Polyglot Swarm[/bold green] v{__version__}")

    backends = settings.configured_backends()
    console.print(f"  Configured backends: {', '.join(backends) or '[red]none[/red]'}")

    problems = validate_settings(settings)
    tiers: tuple[Tier, ...] = ("primary", "fast", "local")
    for tier in tiers:
        provider = get_provider(tier)
        status = "[green]ok[/green]" if provider.is_available() else "[red]unavailable[/red]"
        console.print(f"  Tier {tier:<8}: {status}")

    if problems:
        console.print("[red]Configuration problems:[/red]")
        for p in problems:
            console.print(f"    • {p}")
        raise typer.Exit(code=1)
    console.print("[green]Configuration OK[/green]")


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
    items = asyncio.run(generate_drills(user, language, cefr_level=profile.cefr_for(language)))
    if not items:
        console.print("[dim]No drills yet — have a conversation session first.[/dim]")
        return
    for i, d in enumerate(items, 1):
        console.print(f"[cyan]{i}. ({d['type']}: {d['target']})[/cyan] {d['prompt']}")
        console.print(
            f"   [dim]answer: {d['answer']}"
            + (f"  |  vs {d['confusable']}" if d.get("confusable") else "")
            + "[/dim]"
        )


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
def assess(
    language: str = typer.Option("Spanish", help="Target language name."),
    user: str = typer.Option("cli-user", help="User id."),
) -> None:
    """Show the multidimensional CEFR profile: per-skill band, confidence, evidence."""
    from src.assessment import build_cefr_profile

    prof = build_cefr_profile(user, language)
    console.print(f"[bold green]CEFR profile for {user}[/bold green] - {language}")
    console.print(f"  Overall: [cyan]{prof.overall}[/cyan]")
    if not prof.skills:
        console.print("[dim]No skill evidence yet - have a conversation session first.[/dim]")
        return
    for skill, a in sorted(prof.skills.items()):
        console.print(
            f"  {skill:<12} [cyan]{a.cefr}[/cyan] "
            f"[dim](confidence {a.confidence:.2f}, {a.sample_size} obs)[/dim]"
        )


@app.command()
def plan(
    language: str = typer.Option("Spanish", help="Target language name."),
    user: str = typer.Option("cli-user", help="User id."),
    minutes: float = typer.Option(15.0, help="Minutes available for this session."),
    goal: str = typer.Option("conversational", help="Learning goal (conversational/reading/...)."),
) -> None:
    """Show today's plan: the next best learning actions and why."""
    from src.curriculum import PlanConstraints, plan_next_actions

    constraints = PlanConstraints(time_available_minutes=minutes, goal=goal)
    actions = plan_next_actions(user, language, constraints=constraints)

    console.print(f"[bold green]Today's plan for {user}[/bold green] — {language} ({goal})")
    if not actions:
        console.print("[dim]No plan yet — have a conversation session first.[/dim]")
        return
    for i, a in enumerate(actions, 1):
        console.print(
            f"  [cyan]{i}. {a.type.value}[/cyan] "
            f"[dim]({a.estimated_minutes:g} min, priority {a.priority:.2f})[/dim]"
        )
        console.print(f"     -> {a.target}  -  {a.reason}")


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
            user,
            language if scenario is None else None,
            scenario_id=scenario,
            session_id=f"cli-{uuid.uuid4().hex[:8]}",
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


@experiment_app.command("create")
def experiment_create(
    name: str = typer.Argument(..., help="Experiment name (unique)."),
    variants: str = typer.Option(
        ..., help="Comma-separated variant names, e.g. control,treatment."
    ),
    description: str = typer.Option("", help="Human-readable description."),
) -> None:
    """Create (or update) an experiment definition."""
    from src.memory import experiments

    variant_list = [v.strip() for v in variants.split(",") if v.strip()]
    exp = experiments.create_experiment(name, variant_list, description=description)
    console.print(f"[bold green]Experiment '{exp['name']}'[/bold green] variants={exp['variants']}")


@experiment_app.command("assign")
def experiment_assign(
    name: str = typer.Argument(..., help="Experiment name."),
    user: str = typer.Option(..., help="User id to assign."),
) -> None:
    """Assign (or show) a user's variant for an experiment."""
    from src.memory import experiments

    try:
        variant = experiments.assign(name, user)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"{user} -> [cyan]{variant}[/cyan]")


@experiment_app.command("measure")
def experiment_measure(
    name: str = typer.Argument(..., help="Experiment name."),
    user: str = typer.Option(..., help="User id being measured."),
    point: str = typer.Option(
        ..., help="Measurement point, e.g. pre_test/immediate_post/delayed_7d."
    ),
    language: str = typer.Option("Spanish", help="Target language name."),
    metric: str = typer.Option(
        "overall_cefr_ordinal", help="Metric name to record (default: CEFR band ordinal)."
    ),
) -> None:
    """Record an outcome by snapshotting the learner's current CEFR profile.

    Reuses the existing multidimensional CEFR profile (no separate "test"
    instrument) — the ordinal position of the overall band (A1=0 .. C2=5) is
    recorded as the metric, with the full profile kept in the outcome payload.
    """
    from src.assessment.cefr_profile import CEFR_ORDER, build_cefr_profile
    from src.memory import experiments

    profile = build_cefr_profile(user, language)
    value = float(CEFR_ORDER.index(profile.overall))
    try:
        experiments.record_outcome(name, user, point, metric, value, payload=profile.as_dict())
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"Recorded {metric}={value:g} ({profile.overall}) for {user} at [cyan]{point}[/cyan]"
    )


@experiment_app.command("report")
def experiment_report(
    name: str = typer.Argument(..., help="Experiment name."),
    metric: str = typer.Option("overall_cefr_ordinal", help="Metric name to summarize."),
) -> None:
    """Show mean outcomes by variant and measurement point."""
    from src.memory import experiments

    summary = experiments.summarize_outcomes(name, metric)
    if not summary:
        console.print("[dim]No outcomes recorded yet for this experiment/metric.[/dim]")
        return
    table = Table(title=f"{name} — {metric}")
    table.add_column("Variant")
    table.add_column("Measurement point")
    table.add_column("n")
    table.add_column("mean")
    for variant, by_point in sorted(summary.items()):
        for point, stats in sorted(by_point.items()):
            table.add_row(variant, point, str(stats["n"]), f"{stats['mean']:.3f}")
    console.print(table)


@experiment_app.command("ablation")
def experiment_ablation(
    learners: int = typer.Option(3, help="Synthetic learners per arm."),
    language: str = typer.Option("Spanish", help="Target language for the sessions."),
) -> None:
    """Run the five-arm ablation ladder and show measured learning gain per arm.

    Drives a scripted cohort through each arm's graph (A=conversation-only ..
    E=full system), measures mean skill mastery before/after, records the
    outcomes, and prints the per-arm gain. Runs offline; set
    POLYGLOT_DETERMINISTIC=1 for a fully reproducible run.
    """
    from src.experiments import run_ablation_study, summarize_report

    report = asyncio.run(run_ablation_study(learners_per_arm=learners, language=language))
    console.print(summarize_report(report))


@experiment_app.command("due")
def experiment_due(
    name: str = typer.Argument(..., help="Experiment name."),
) -> None:
    """List delayed measurements (1d/7d/30d) that are due but not yet recorded.

    This is the producer that makes delayed-retention measurement real: a
    scheduled job (or an operator) runs this, then records each due point via
    `polyglot experiment measure`.
    """
    from src.memory import experiments

    due = experiments.due_measurements(name)
    if not due:
        console.print("[dim]No delayed measurements are due right now.[/dim]")
        return
    table = Table(title=f"{name} — due delayed measurements")
    table.add_column("User")
    table.add_column("Variant")
    table.add_column("Point")
    table.add_column("Due at")
    for item in due:
        table.add_row(item["user_id"], item["variant"], item["measurement_point"], item["due_at"])
    console.print(table)


@security_app.command("backup")
def security_backup(
    label: str | None = typer.Option(None, help="Optional short tag for the backup filename."),
) -> None:
    """Create a timestamped backup of the SQLite database."""
    from src.security.backup import create_backup

    path = create_backup(label=label)
    console.print(f"[bold green]Backup created:[/bold green] {path}")


@security_app.command("backups")
def security_backups() -> None:
    """List existing database backups, most recent first."""
    from src.security.backup import list_backups

    backups = list_backups()
    if not backups:
        console.print("[dim]No backups yet. Run `polyglot security backup` to create one.[/dim]")
        return
    for path in backups:
        console.print(str(path))


@security_app.command("audit")
def security_audit(
    user: str | None = typer.Option(None, help="Filter by user id."),
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type."),
    limit: int = typer.Option(20, help="Max entries to show."),
) -> None:
    """Show recent security audit-log entries."""
    from src.security.audit import recent_events

    events = recent_events(user_id=user, event_type=event_type, limit=limit)
    if not events:
        console.print("[dim]No audit-log entries recorded yet.[/dim]")
        return
    table = Table(title="Audit log")
    table.add_column("Time")
    table.add_column("Event")
    table.add_column("User")
    table.add_column("Detail")
    for e in events:
        table.add_row(
            str(e.get("created_at", "")),
            str(e.get("event_type", "")),
            str(e.get("user_id") or "-"),
            str(e.get("detail", {})),
        )
    console.print(table)


@privacy_app.command("export")
def privacy_export(
    user: str = typer.Argument(..., help="User id to export data for."),
    output: str | None = typer.Option(None, help="Write JSON to this file instead of printing it."),
) -> None:
    """Export everything stored about a user as JSON."""
    import json as _json

    from src.memory.privacy import export_user_data

    data = export_user_data(user)
    payload = _json.dumps(data, indent=2, default=str)
    if output:
        Path(output).write_text(payload, encoding="utf-8")
        console.print(f"[bold green]Exported to {output}[/bold green]")
    else:
        console.print(payload, markup=False)


@privacy_app.command("delete")
def privacy_delete(
    user: str = typer.Argument(..., help="User id to delete all data for."),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
) -> None:
    """Permanently delete every stored record for a user (irreversible)."""
    from src.memory.privacy import delete_user_data

    if not yes:
        confirmed = typer.confirm(
            f"This will permanently delete ALL data for user {user!r}. Continue?"
        )
        if not confirmed:
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(code=1)

    result = delete_user_data(user)
    console.print(f"[bold green]Deleted data for {user}:[/bold green]")
    for store, outcome in result.items():
        console.print(f"  {store}: {outcome}")


@cost_app.command("session")
def cost_session(
    session_id: str = typer.Argument(..., help="Session id to summarize."),
    user: str | None = typer.Option(None, help="Scope to this user (recommended)."),
) -> None:
    """Show LLM cost/latency for one session, broken down by tier."""
    from src.llm.cost import session_cost

    summary = session_cost(session_id, user)
    _print_cost_summary(f"session {session_id}", summary)


@cost_app.command("user")
def cost_user(user: str = typer.Argument(..., help="User id to summarize.")) -> None:
    """Show LLM cost/latency across all of a user's sessions, by tier."""
    from src.llm.cost import user_cost

    summary = user_cost(user)
    _print_cost_summary(f"user {user}", summary)


def _print_cost_summary(label: str, summary: Any) -> None:
    d = summary.as_dict()
    console.print(f"[bold green]Cost for {label}[/bold green]")
    console.print(f"  calls: {d['calls']}  tokens: {d['tokens']}  cost: ${d['cost_usd']:.6f}")
    console.print(f"  mean latency: {d['mean_latency_ms']:.1f} ms  failures: {d['failures']}")
    if d["by_tier"]:
        table = Table(title="By tier")
        table.add_column("Tier")
        table.add_column("Calls")
        table.add_column("Tokens")
        table.add_column("Cost")
        table.add_column("Failures")
        for tier, bucket in sorted(d["by_tier"].items()):
            table.add_row(
                tier,
                str(bucket["calls"]),
                str(bucket["tokens"]),
                f"${bucket['cost_usd']:.6f}",
                str(bucket["failures"]),
            )
        console.print(table)


@app.command()
def trace(
    session_id: str = typer.Argument(..., help="Session id to reconstruct."),
    user: str = typer.Option("cli-user", help="User id (sessions are per-user)."),
    language: str | None = typer.Option(None, help="Filter evidence by language."),
) -> None:
    """Reconstruct a session's trace: LLM calls + evidence, ordered and correlated."""
    from src.observability.trace import assemble_trace, format_trace

    result = assemble_trace(user, session_id, language=language)
    # markup=False: the trace text contains literal "[...]" section headers
    # (e.g. "[interaction ...]") that are not Rich style tags.
    console.print(format_trace(result), markup=False)


if __name__ == "__main__":
    app()
