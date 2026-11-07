"""Polyglot Swarm command-line interface.

Exposed as the ``polyglot`` console script. Provides:
- ``polyglot scenarios`` — list the available scenarios.
- ``polyglot chat`` — an interactive terminal conversation session, optionally
  driven by a scenario.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any, TextIO

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from src.observability.logging_config import ensure_configured
from src.orchestrator.lifecycle import build_initial_state, finalize_session
from src.orchestrator.state import LearnerState
from src.scenarios.loader import ScenarioError, list_scenarios

# Phase 23: configure logging once, at process start, before any command runs
# — so every polyglot.* logger actually produces visible output (level/format
# controlled by settings.log_level/log_format) rather than being silently
# dropped by Python's logging "handler of last resort".
ensure_configured()


def _ensure_utf8_output(*streams: TextIO) -> None:
    """Stop non-UTF-8 consoles (e.g. a Windows cp1252 pipe) from crashing on emoji.

    Rich writes the banner's 🌍 and the report's symbols as-is; on an encoding
    that can't represent them the whole command dies with UnicodeEncodeError.
    """
    for stream in streams:
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding != "utf8" and reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass  # a stream that can't be reconfigured keeps its encoding


_ensure_utf8_output(sys.stdout, sys.stderr)

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

ops_app = typer.Typer(help="Operations: verified backups, restore, maintenance, DB checks.")
app.add_typer(ops_app, name="ops")


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


_NO_BACKEND_HELP = (
    "No working LLM backend. Pick one, then run `polyglot health` again:\n"
    "  1. Put an API key in .env (ANTHROPIC_API_KEY, GOOGLE_API_KEY or OPENAI_API_KEY)\n"
    "  2. Run Ollama locally and pull the model (see the fix above)\n"
    "  3. Set POLYGLOT_DETERMINISTIC=1 in .env for an offline demo with canned replies\n"
    "Step-by-step setup: README.md -> Quick start."
)


def _print_backend_checks(checks: list[Any]) -> None:
    for check in checks:
        mark = "[green]ok  [/green]" if check.ok else "[red]FAIL[/red]"
        console.print(f"  {mark} {check.name:<13} {check.detail}")
        if check.fix:
            console.print(f"       [yellow]fix:[/yellow] {check.fix}")


@app.command()
def health() -> None:
    """Check that setup is complete and an LLM backend can actually answer.

    Asks a local Ollama which models it has (hosted API keys are reported as
    set, not verified). Exits non-zero when no backend works, so it is usable
    as a readiness check in scripts and CI.
    """
    from src import __version__
    from src.config import settings, validate_settings
    from src.llm.preflight import check_backends, has_usable_backend

    console.print(f"[bold green]Polyglot Swarm[/bold green] v{__version__}")
    # In a container the settings arrive as environment variables (compose's
    # env_file), so a missing .env file there is expected.
    if not Path(".env").exists() and not Path("/.dockerenv").exists():
        console.print(
            "  [yellow]No .env file in this folder[/yellow] - copy .env.example to .env "
            "to configure the app (defaults are used until then)."
        )

    console.print("LLM backends:")
    checks = check_backends(settings)
    _print_backend_checks(checks)

    problems = validate_settings(settings)
    if problems or not has_usable_backend(checks):
        for p in problems:
            console.print(f"[red]Configuration problem:[/red] {p}")
        console.print(f"[red]{_NO_BACKEND_HELP}[/red]")
        raise typer.Exit(code=1)
    console.print("[green]Ready - try: polyglot chat --language Spanish[/green]")


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


async def _chat_loop(state: LearnerState, speaker: str) -> dict[str, Any] | None:
    """Run the interactive session in one event loop, then finalize it.

    Uses the API's turn runner: the reply prints as soon as the tutor answers,
    and the turn's grammar/vocabulary/cultural analysis and the evaluator run
    in the background while the learner types the next message. The next
    turn and the finalization wait for it, so CLI sessions record learning
    evidence and adapt difficulty exactly like API sessions.
    """
    from src.api.sessions import finalize, run_turn

    while True:
        try:
            user_input = await asyncio.to_thread(console.input, "[cyan]You:[/cyan] ")
        except EOFError:
            break
        if user_input.strip().lower() in {"quit", "exit"}:
            break
        result = await run_turn(state, user_input)
        console.print(f"[bold]{speaker}:[/bold] {escape(result.reply)}\n")

    console.print("\n[dim]Ending session...[/dim]")
    return await finalize(state["user_id"], state["session_id"], state=state)


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
    overall = prof.overall or "not yet assessed"
    console.print(f"  Overall: [cyan]{overall}[/cyan] [dim]({prof.overall_status})[/dim]")
    if not prof.skills:
        console.print("[dim]No skill evidence yet - have a conversation session first.[/dim]")
        return
    for skill, a in sorted(prof.skills.items()):
        band = a.cefr or "-"
        if a.mastery_low is not None and a.mastery_high is not None:
            span = f"mastery {a.mastery_low:.2f}-{a.mastery_high:.2f}, "
        else:
            span = ""
        console.print(
            f"  {skill:<12} [cyan]{band:<3}[/cyan] {a.status:<22} "
            f"[dim]({span}{a.independent_count} independent / {a.sample_size} obs, "
            f"evidence {a.confidence_label})[/dim]"
        )
    if prof.unassessed_skills:
        console.print(f"  [dim]Not yet assessed: {', '.join(prof.unassessed_skills)}[/dim]")
    console.print(
        "  [dim]Bands come from a fixed mastery curve; evidence labels are not "
        "calibrated probabilities.[/dim]"
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
        intent = f"{a.intent}, " if a.intent else ""
        console.print(
            f"  [cyan]{i}. {a.type.value}[/cyan] "
            f"[dim]({intent}{a.estimated_minutes:g} min, priority {a.priority:.2f})[/dim]"
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
    from src.llm.preflight import check_backends, has_usable_backend

    # Without a working backend every turn would get the same canned fallback
    # reply, which looks like the tutor is broken rather than unconfigured.
    checks = check_backends()
    if not has_usable_backend(checks):
        _print_backend_checks(checks)
        console.print(f"[red]{_NO_BACKEND_HELP}[/red]")
        raise typer.Exit(code=1)

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

    scenario_ctx = state.get("current_scenario", {}) or {}
    persona = scenario_ctx.get("persona", {})
    # Model output and scenario text are printed verbatim, never as Rich markup:
    # otherwise "[ser]" in a reply (or the fake provider's "[fake:...]") vanishes.
    speaker = escape(persona.get("name", "Tutor"))
    console.print(
        f"[bold green]🌍 Polyglot Swarm[/bold green] — {state['language']} | "
        f"Working level: {state['cefr_level']}"
    )
    opening = scenario_ctx.get("opening_line")
    if opening:
        console.print(f"[bold]{speaker}:[/bold] {escape(opening)}")
    console.print("[dim](type 'quit' to end and see your report)[/dim]\n")

    from src.api.sessions import finalize

    try:
        result = asyncio.run(_chat_loop(state, speaker))
    except KeyboardInterrupt:
        # Ctrl+C cancels the loop; a cut-short analysis re-runs in finalize.
        console.print("\n[dim]Ending session...[/dim]")
        result = asyncio.run(finalize(state["user_id"], state["session_id"], state=state))
    if result is None:
        # No turn was taken, so there is no snapshot to claim.
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

    if experiments.get_assignment(name, user) is None:
        console.print(f"[red]no variant assignment for {user!r} in {name!r}[/red]")
        raise typer.Exit(code=1)
    profile = build_cefr_profile(user, language)
    if profile.overall is None:
        # ADR-0031: never record a fabricated level as an outcome.
        console.print(f"[red]No overall CEFR level for {user} ({profile.overall_status}).[/red]")
        console.print("No outcome recorded - gather more evidence first.")
        raise typer.Exit(code=1)
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


# --- Operations (Phase 5, ADR-0035; see docs/production/operations-runbook.md) ---


@ops_app.command("backup")
def ops_backup(
    label: str | None = typer.Option(None, help="Short tag in the backup set name."),
    prune: bool = typer.Option(True, help="Apply BACKUP_RETENTION_COUNT afterwards."),
) -> None:
    """Write and verify a backup set (database, media, profiles)."""
    from src.ops.backup import create_backup_set, prune_backups

    path = create_backup_set(label=label)
    console.print(f"[bold green]Verified backup set:[/bold green] {path}")
    if prune:
        for old in prune_backups():
            console.print(f"[dim]pruned {old.name}[/dim]")


@ops_app.command("backups")
def ops_backups() -> None:
    """List backup sets, newest first, with their row counts."""
    import json

    from src.ops.backup import MANIFEST, list_backup_sets

    sets = list_backup_sets()
    if not sets:
        console.print("[dim]No backup sets. Run `polyglot ops backup`.[/dim]")
        return
    for path in sets:
        manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        console.print(f"{path.name}  v{manifest['schema_version']}  {manifest['row_counts']}")


@ops_app.command("verify")
def ops_verify(path: Path = typer.Argument(..., help="Backup set directory.")) -> None:
    """Re-verify a backup set (checksums and SQLite integrity)."""
    from src.ops.backup import BackupError, verify_backup_set

    try:
        manifest = verify_backup_set(path)
    except BackupError as exc:
        console.print(f"[bold red]FAILED:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]OK[/green] {path.name}: {manifest['row_counts']}")


@ops_app.command("restore")
def ops_restore(
    path: Path = typer.Argument(..., help="Backup set directory."),
    yes: bool = typer.Option(False, "--yes", help="Confirm: the API is stopped."),
) -> None:
    """Restore a backup set over the live data. Stop the API first."""
    from src.ops.backup import BackupError, restore_backup_set

    if not yes:
        console.print("Refusing without --yes. Stop the API, then re-run with --yes.")
        raise typer.Exit(code=2)
    try:
        manifest = restore_backup_set(path)
    except BackupError as exc:
        console.print(f"[bold red]Restore failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[bold green]Restored[/bold green] {path.name}: {manifest['row_counts']}")


@ops_app.command("maintenance")
def ops_maintenance() -> None:
    """Run recovery and housekeeping once (idle sessions, tokens, media, keys)."""
    from src.memory import schema
    from src.ops.maintenance import run_maintenance

    schema.init_all()
    console.print(asyncio.run(run_maintenance()))


@ops_app.command("db-check")
def ops_db_check() -> None:
    """Exit non-zero unless the database is intact and at the expected schema."""
    import sqlite3

    from src.config import settings
    from src.memory import schema

    conn = sqlite3.connect(settings.db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()
    ok = integrity == "ok" and version == schema.SCHEMA_VERSION
    console.print(
        f"integrity={integrity} schema={version} expected={schema.SCHEMA_VERSION} "
        + ("[green]OK[/green]" if ok else "[red]NOT OK[/red]")
    )
    if not ok:
        raise typer.Exit(code=1)


@ops_app.command("config-check")
def ops_config_check() -> None:
    """Validate configuration for APP_ENV (exit 1 on any problem)."""
    from src.config import settings, validate_settings

    problems = validate_settings(settings)
    for problem in problems:
        console.print(f"[red]-[/red] {problem}")
    if problems:
        raise typer.Exit(code=1)
    console.print(f"[green]configuration OK for APP_ENV={settings.app_env}[/green]")


if __name__ == "__main__":
    app()
