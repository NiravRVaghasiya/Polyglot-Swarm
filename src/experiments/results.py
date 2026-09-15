"""Reproducible results-artifact generator (Gate C: published results).

Runs the three measurement harnesses the project already has — the benchmark
harness (:mod:`benchmarks.harness`), the evaluation harness
(:mod:`evals.harness`), and the ablation study runner
(:mod:`src.experiments.runner`) — collects their *actual measured numbers*,
and renders a single ``docs/results.md`` artifact. This closes the audit gap
where the plan's "published results" existed only as unchecked checkboxes:
the numbers in the artifact are produced by running the system, not written by
hand, and the artifact carries the command to regenerate it.

Everything runs in deterministic mode against isolated temp storage, so the
artifact is reproducible on any machine with no API keys, network, or real
``./data``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Where the generated artifact is written, relative to the repo root.
DEFAULT_OUTPUT = Path("docs/results.md")

#: A short, honest catalogue of what the numbers below do and do not show.
#: Kept in code (not a static doc) so it is regenerated alongside the numbers
#: and cannot drift out of sync with how they were produced.
_KNOWN_LIMITATIONS = [
    "All numbers are produced in DETERMINISTIC mode (`POLYGLOT_DETERMINISTIC=1`): "
    "LLM calls resolve to a fake/scripted provider, not a live model. They "
    "measure the surrounding machinery, decision logic, and pipeline wiring — "
    "NOT live-model quality. Real-model precision/recall/latency will differ.",
    "The grammar false-correction-rate benchmark runs on a small, hand-labeled "
    "case set against the deterministic classification/abstention policy "
    "(`grammar._select_errors`), so it validates the policy, not end-to-end "
    "model behavior on a large corpus.",
    "The ablation study uses a scripted single-session 'lesson' and synthetic "
    "learners. It demonstrates that the analysis pipeline (arms D/E) produces "
    "measurable learner-model evidence that conversation-only arms (A/B/C) do "
    "not — a wiring/attribution result, not a claim about human learning gains.",
    "Delayed-retention measurement (1d/7d/30d) is wired end to end "
    "(`experiments.due_measurements` produces the due work list), but no "
    "longitudinal study with real learners over real calendar time has been "
    "run — so no delayed-retention numbers are reported here yet.",
    "CEFR estimates are model-internal, derived from the accumulated evidence; "
    "they have NOT been validated against expert human raters or an "
    "established language test. Correlation-with-experts numbers are therefore "
    "absent by design until such a study exists.",
    "Cost figures are estimates from a static per-model price table "
    "(`llm.telemetry.estimate_cost`), not billed amounts, and are $0 in "
    "deterministic mode since the fake provider is free.",
]


async def collect_results(*, learners_per_arm: int = 3) -> dict[str, Any]:
    """Run all three harnesses and return their measured results as data.

    Uses isolated temp storage for the eval/ablation runs so the developer's
    real ``./data`` is never touched. Assumes deterministic mode is active (the
    caller / CLI sets ``POLYGLOT_DETERMINISTIC=1``); it is verified and
    recorded in the returned metadata.
    """
    from benchmarks.harness import run_benchmarks
    from evals.harness import run_evals
    from src.llm.fake import is_deterministic

    benchmark_results = await run_benchmarks()
    eval_results = await run_evals()

    # The ablation run needs isolated storage of its own (it writes evidence /
    # skill beliefs / outcomes), separate from the eval suites' storage.
    ablation_report, ablation_text = await _run_ablation_isolated(learners_per_arm)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "deterministic": is_deterministic(),
        "benchmarks": [_result_row(r) for r in benchmark_results],
        "evals": [_eval_row(r) for r in eval_results],
        "ablation": ablation_report.as_dict(),
        "ablation_text": ablation_text,
    }


async def _run_ablation_isolated(learners_per_arm: int) -> tuple[Any, str]:
    from src.config import settings
    from src.experiments.runner import run_ablation_study, summarize_report

    original = {
        "data_dir": settings.data_dir,
        "db_path": settings.db_path,
        "profiles_dir": settings.profiles_dir,
        "chroma_path": settings.chroma_path,
    }
    tmp_dir = Path(tempfile.mkdtemp(prefix="polyglot-results-"))
    data_dir = tmp_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir = str(data_dir)
    settings.db_path = str(data_dir / "polyglot.db")
    settings.profiles_dir = str(data_dir / "profiles")
    settings.chroma_path = str(data_dir / "chroma")
    try:
        report = await run_ablation_study(learners_per_arm=learners_per_arm)
        return report, summarize_report(report)
    finally:
        for key, value in original.items():
            setattr(settings, key, value)
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _result_row(r: Any) -> dict[str, Any]:
    return {
        "name": r.name,
        "passed": r.passed,
        "duration_ms": round(r.duration_ms, 2),
        "metrics": dict(r.metrics),
    }


def _eval_row(r: Any) -> dict[str, Any]:
    return {
        "suite": r.suite,
        "name": r.name,
        "passed": r.passed,
        "duration_ms": round(r.duration_ms, 2),
        "metrics": dict(r.metrics),
    }


def render_markdown(data: dict[str, Any]) -> str:
    """Render collected results as the ``docs/results.md`` artifact."""
    lines: list[str] = []
    lines.append("# Measured results")
    lines.append("")
    lines.append(
        "> Generated by `polyglot results` (`python -m src.cli results`). "
        "Do not edit by hand — regenerate instead."
    )
    lines.append("")
    lines.append(f"- Generated at: `{data['generated_at']}`")
    lines.append(f"- Deterministic mode: `{data['deterministic']}`")
    lines.append("")
    lines.append(
        "These are actual numbers produced by running the project's measurement "
        "harnesses, not hand-written claims. See **Known limitations** at the "
        "bottom for exactly what they do and do not demonstrate."
    )
    lines.append("")

    # --- Benchmarks ---
    lines.append("## Component benchmarks")
    lines.append("")
    lines.append("| Benchmark | Result | Duration (ms) | Key metrics |")
    lines.append("|---|---|---|---|")
    for b in data["benchmarks"]:
        lines.append(
            f"| `{b['name']}` | {_ok(b['passed'])} | {b['duration_ms']:.2f} | "
            f"{_fmt_metrics(b['metrics'])} |"
        )
    lines.append("")

    # --- Evals ---
    lines.append("## Evaluation suites")
    lines.append("")
    lines.append("| Suite | Eval | Result | Key metrics |")
    lines.append("|---|---|---|---|")
    for e in data["evals"]:
        suite = e["suite"].rsplit(".", 2)[-2] if "." in e["suite"] else e["suite"]
        lines.append(
            f"| {suite} | `{e['name']}` | {_ok(e['passed'])} | {_fmt_metrics(e['metrics'])} |"
        )
    lines.append("")

    # --- Ablation ---
    ablation = data["ablation"]
    lines.append("## Ablation study (which components create learning signal)")
    lines.append("")
    lines.append(
        f"Experiment `{ablation['experiment']}`, metric `{ablation['metric']}` "
        "(mean learner-model mastery over grammar + vocabulary, in [0, 1]). "
        "Each arm runs a scripted cohort through a different graph topology; "
        "the gain is post-session minus pre-session mastery."
    )
    lines.append("")
    lines.append("| Arm | Description | n | pre | post | gain |")
    lines.append("|---|---|---|---|---|---|")
    descriptions = {
        "A": "conversation only",
        "B": "conversation + memory",
        "C": "conversation + FSRS review",
        "D": "conversation + analysis (learner model)",
        "E": "full system",
    }
    for arm in ablation["arms"]:
        lines.append(
            f"| {arm['arm']} | {descriptions.get(arm['arm'], '')} | {arm['n_learners']} | "
            f"{arm['mean_pre']:.3f} | {arm['mean_post']:.3f} | {arm['mean_gain']:+.3f} |"
        )
    lines.append("")
    lines.append(
        "The arms without the analysis pipeline (A/B/C) accumulate no "
        "learner-model evidence and show zero gain; the arms with it (D/E) show "
        "a positive gain. That is the ablation's intended result: the learner-"
        "model analysis components are what turn a conversation into measurable "
        "evidence about the learner."
    )
    lines.append("")

    # --- Known limitations ---
    lines.append("## Known limitations")
    lines.append("")
    for item in _KNOWN_LIMITATIONS:
        lines.append(f"- {item}")
    lines.append("")

    # --- Reproduce ---
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("POLYGLOT_DETERMINISTIC=1 python -m src.cli results")
    lines.append("# or, to print without writing the file:")
    lines.append("POLYGLOT_DETERMINISTIC=1 python -m src.cli results --stdout")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _ok(passed: bool) -> str:
    return "pass" if passed else "**FAIL**"


def _fmt_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "—"
    parts = []
    for key, value in metrics.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:.3f}")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


async def generate(
    *,
    output: Path | None = None,
    learners_per_arm: int = 3,
    write: bool = True,
) -> str:
    """Collect results and render the markdown, optionally writing the file.

    Returns the rendered markdown. When ``write`` is true, also writes it to
    ``output`` (default :data:`DEFAULT_OUTPUT`).
    """
    if not os.getenv("POLYGLOT_DETERMINISTIC"):
        # Make the reproducibility guarantee real: the artifact is defined to
        # be a deterministic offline run, so refuse to generate a "results"
        # file from live, non-reproducible model calls.
        raise RuntimeError(
            "Results generation requires deterministic mode. "
            "Set POLYGLOT_DETERMINISTIC=1 before running."
        )
    data = await collect_results(learners_per_arm=learners_per_arm)
    markdown = render_markdown(data)
    if write:
        target = output or DEFAULT_OUTPUT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    return markdown
