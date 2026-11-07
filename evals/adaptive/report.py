"""Markdown rendering for the adaptive-learning evaluations (SIMULATED)."""

from __future__ import annotations

import math
from typing import Any

BANNER = (
    "> **Simulated learners.** Every number below comes from the simulator in "
    "`evals/adaptive/simulator.py` and reflects its assumptions. None of it is "
    "a real learner outcome."
)


def _f(v: Any, digits: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:.{digits}f}"


def _ci(entry: dict[str, Any]) -> str:
    lo, hi = entry["ci95"]
    return f"{_f(entry['value'])} [{_f(lo)}, {_f(hi)}]"


REAL_BANNER = (
    "> **Real learner evidence.** Targets are the graded (observed) outcomes, which "
    "include grading noise; there is no hidden ground truth."
)


def render_models(data: dict[str, Any]) -> str:
    simulated = data.get("simulated", True)
    if simulated:
        cfg = data["config"]
        title = f"# Learner-model comparison — `{cfg['family']}` generator"
        setup = (
            f"- {cfg['n_sessions']} sessions x {cfg['attempts_per_session']} attempts each; "
            "target = the learner's true outcome."
        )
    else:
        title = f"# Learner-model comparison — real evidence (`{data.get('source', '?')}`)"
        setup = "- Target = the graded outcome of each attempt."
    lines = [
        title,
        "",
        BANNER if simulated else REAL_BANNER,
        "",
        f"- Train learners: {data['n_train_learners']}; test learners: {data['n_test_learners']}.",
        setup,
        f"- Held-out predictions: {data['n_test_predictions']} (online: each attempt is "
        "predicted before it is observed).",
        "- 95% intervals: learner-level bootstrap.",
        "",
    ]
    for regime, results in data["regimes"].items():
        lines += [
            f"## Regime: {regime}",
            "",
            "| model | AUC | log loss | Brier | ECE |",
            "|---|---|---|---|---|",
        ]
        for name, e in results.items():
            lines.append(
                f"| {name} | {_ci(e['auc'])} | {_ci(e['log_loss'])} | "
                f"{_ci(e['brier'])} | {_ci(e['ece'])} |"
            )
        lines += ["", "Paired difference vs `lkm_v2_rasch` (model minus baseline):", ""]
        lines += ["| model | AUC diff [95% CI] | log-loss diff [95% CI] |", "|---|---|---|"]
        for name, e in results.items():
            vb = e.get("vs_baseline")
            if not vb:
                continue
            a, ll = vb["auc"], vb["log_loss"]
            lines.append(
                f"| {name} | {_f(a['difference'])} [{_f(a['ci_low'])}, {_f(a['ci_high'])}] | "
                f"{_f(ll['difference'])} [{_f(ll['ci_low'])}, {_f(ll['ci_high'])}] |"
            )
        sub = results.get("lkm_subskill_v1", {})
        if sub.get("vs_elo"):
            ve = sub["vs_elo"]
            lines += [
                "",
                "`lkm_subskill_v1` minus `elo`: "
                + ", ".join(
                    f"{m} {_f(ve[m]['difference'])} [{_f(ve[m]['ci_low'])}, {_f(ve[m]['ci_high'])}]"
                    for m in ("auc", "log_loss", "ece")
                ),
            ]
        if sub.get("uncertainty"):
            u = sub["uncertainty"]
            lines += [
                "",
                f"`lkm_subskill_v1` 95% prediction intervals contain the true success "
                f"probability {_f(u['interval_coverage'])} of the time (mean width "
                f"{_f(u['mean_interval_width'])}).",
            ]
        if sub.get("selected_config"):
            sc = sub["selected_config"]
            lines.append(
                f"Tuned on training learners: half-life {sc['subskill_half_life_days']} days, "
                f"offset prior SD {sc['offset_prior_sd']}."
            )
        lines += ["", "By prior evidence on the subskill (AUC / log loss):", ""]
        lines += ["| model | 0 prior | 1-3 prior | 4+ prior |", "|---|---|---|---|"]
        for name, e in results.items():
            b = e["by_prior_evidence"]
            lines.append(
                f"| {name} | "
                + " | ".join(
                    f"{_f(b[k]['auc'])} / {_f(b[k]['log_loss'])} (n={b[k]['n']})"
                    for k in ("0", "1-3", "4+")
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def _peak(value: float | None) -> str:
    return "flat (difficulty does not matter)" if value is None else str(value)


def _diff(d: dict[str, float]) -> str:
    return f"{_f(d['difference'])} [{_f(d['ci_low'])}, {_f(d['ci_high'])}]"


def render_policies(data: dict[str, Any]) -> str:
    cfg = data["config"]
    lines = [
        "# Adaptive learning outcomes — policy simulation",
        "",
        BANNER,
        "",
        f"- Generator: `{cfg['family']}`, gain peak {_peak(cfg['gain_peak'])}.",
        f"- {cfg['n_learners']} simulated learners, {cfg['n_sessions']} sessions of "
        f"{cfg['session_minutes']} minutes; delayed tests at +{cfg['delay_days']} days after "
        "the last session with no practice in between.",
        "- Every policy faces the same learners with common random numbers; "
        "differences are paired per learner (bootstrap 95% CI).",
        "",
        "| metric | " + " | ".join(data["policies"]) + " |",
        "|---|" + "---|" * len(data["policies"]),
    ]
    for metric in data["metrics"]:
        row = [metric]
        for pol in data["policies"]:
            e = data["results"][pol][metric]
            row.append(f"{_f(e['mean'])} [{_f(e['ci95'][0])}, {_f(e['ci95'][1])}]")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", f"Paired differences against `{data['baseline']}` (policy minus baseline):", ""]
    lines += [
        "| policy | " + " | ".join(data["key_metrics"]) + " |",
        "|---|" + "---|" * len(data["key_metrics"]),
    ]
    for pol, diffs in data["vs_baseline"].items():
        lines.append(
            f"| {pol} | " + " | ".join(_diff(diffs[m]) for m in data["key_metrics"]) + " |"
        )
    if data.get("ablations"):
        metrics = list(next(iter(data["ablations"].values())))
        lines += [
            "",
            "Paired differences isolating one capability (policy minus its baseline):",
            "",
            "| comparison | " + " | ".join(metrics) + " |",
            "|---|" + "---|" * len(metrics),
        ]
        for name, diffs in data["ablations"].items():
            lines.append(f"| {name} | " + " | ".join(_diff(diffs[m]) for m in metrics) + " |")
    if data.get("prediction"):
        p = data["prediction"]
        lines += [
            "",
            "## Prediction accuracy inside the adaptive policy",
            "",
            f"- Next-attempt success predictions (made before each attempt): n={p['n']}, "
            f"AUC {_f(p['auc'])}, log loss {_f(p['log_loss'])}, Brier {_f(p['brier'])}, "
            f"ECE {_f(p['ece'])}.",
        ]
        if p.get("retention"):
            r = p["retention"]
            lines.append(
                f"- Delayed-recall predictions for vocabulary (FSRS retrievability at the "
                f"delayed test vs the true recall probability): n={r['n']}, mean predicted "
                f"{_f(r['mean_predicted'])}, mean true {_f(r['mean_true'])}, rank correlation "
                f"{_f(r['spearman'])}."
            )
    lines.append("")
    lines.append(
        "Metric definitions are in `docs/adaptive-learning.md`. Immediate performance and "
        "delayed retention are measured separately: immediate = outcomes during sessions; "
        "delayed = true recall probability after the delay."
    )
    return "\n".join(lines) + "\n"
