"""Historical tracking and regression detection between evaluation runs.

``history.jsonl`` gets one line per (run, provider) with the headline metrics
and the identity needed to know whether two lines are comparable (dataset
version + checksum, prompt versions, config hash, synthetic flag).

:func:`compare_runs` compares two runs on the cases they share, per provider
and prompt name. The decision uses the **exact McNemar test on paired
case-level correctness**:

- ``regression``: the candidate is worse and ``p < alpha``;
- ``improvement``: the candidate is better and ``p < alpha``;
- ``no_significant_change``: otherwise — a different point estimate alone is
  never called a regression;
- ``incomparable``: different dataset version/split, or mixing synthetic with
  real results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.real.config import EvalConfig
from src.evaluation.statistics import mcnemar_exact

HISTORY_PATH = Path(__file__).parent / "history.jsonl"
_HEADLINE = (
    ("grammar", "precision"),
    ("grammar", "recall"),
    ("grammar", "false_correction_rate"),
    ("structured", "schema_valid_rate"),
)


def record_history(report: dict[str, Any], path: Path = HISTORY_PATH) -> int:
    """Append (or replace) this run's lines in the history file. Returns lines written."""
    existing: list[dict[str, Any]] = []
    if path.exists():
        existing = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    existing = [e for e in existing if e.get("run_id") != report["run_id"]]
    new = []
    for prov_key, m in sorted(report["providers"].items()):
        if "grammar" not in m:
            continue
        new.append(
            {
                "run_id": report["run_id"],
                "created_at": report["created_at"],
                "status": report["status"],
                "synthetic": report["synthetic"],
                "provider": prov_key,
                "config_hash": report["config_hash"],
                "dataset": report["datasets"].get("grammar"),
                "prompts": {k: v["sha256"][:12] for k, v in report["prompts"].items()},
                "metrics": {f"{s}.{n}": m[s][n] for s, n in _HEADLINE},
            }
        )
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in [*existing, *new]),
        encoding="utf-8",
    )
    return len(new)


def compare_runs(base_dir: Path, cand_dir: Path, *, alpha: float | None = None) -> dict[str, Any]:
    from evals.real.report import score_run

    base, cand = score_run(base_dir), score_run(cand_dir)
    bm, cm = base["manifest"], cand["manifest"]
    alpha = alpha if alpha is not None else EvalConfig.model_validate(cm["config"]).regression_alpha
    reasons = []
    bg, cg = bm["datasets"].get("grammar"), cm["datasets"].get("grammar")
    if not bg or not cg:
        reasons.append("one of the runs has no grammar task")
    elif (bg["version"], bg["split"]) != (cg["version"], cg["split"]):
        reasons.append(
            f"different datasets: {bg['version']}/{bg['split']} vs {cg['version']}/{cg['split']}"
        )
    if bm["synthetic"] != cm["synthetic"]:
        reasons.append("cannot compare a synthetic run with a real-model run")
    result: dict[str, Any] = {
        "base": bm["run_id"],
        "candidate": cm["run_id"],
        "alpha": alpha,
        "comparable": not reasons,
        "reasons": reasons,
        "comparisons": [],
    }
    if reasons:
        return result
    cases = cand["grammar_cases"]

    def by_name(
        groups: dict[tuple[str, str], list[Any]],
    ) -> dict[tuple[str, str], tuple[str, list[Any]]]:
        return {(p, prompt.split("@")[0]): (prompt, outs) for (p, prompt), outs in groups.items()}

    bmap, cmap = by_name(base["grammar"]), by_name(cand["grammar"])
    for key in sorted(set(bmap) & set(cmap)):
        bprompt, bouts = bmap[key]
        cprompt, couts = cmap[key]
        bx = {o.case_id: o for o in bouts if o.ok and o.repeat == 0}
        cx = {o.case_id: o for o in couts if o.ok and o.repeat == 0}
        common = sorted(c for c in set(bx) & set(cx) if cases[c].has_error is not None)
        b = sum(1 for c in common if bx[c].detection_correct and not cx[c].detection_correct)
        c_ = sum(1 for c in common if not bx[c].detection_correct and cx[c].detection_correct)
        p = mcnemar_exact(b, c_)
        if p < alpha and b > c_:
            decision = "regression"
        elif p < alpha and c_ > b:
            decision = "improvement"
        else:
            decision = "no_significant_change"
        fp_b = sum(1 for c in common if not cases[c].has_error and bx[c].predicted_error)
        fp_c = sum(1 for c in common if not cases[c].has_error and cx[c].predicted_error)
        negatives = sum(1 for c in common if not cases[c].has_error)
        result["comparisons"].append(
            {
                "provider": key[0],
                "prompt": {"base": bprompt, "candidate": cprompt},
                "cases": len(common),
                "base_correct": sum(1 for c in common if bx[c].detection_correct),
                "candidate_correct": sum(1 for c in common if cx[c].detection_correct),
                "base_only_correct": b,
                "candidate_only_correct": c_,
                "p_value": round(p, 4),
                "false_corrections": {"base": fp_b, "candidate": fp_c, "of": negatives},
                "decision": decision,
            }
        )
    return result
