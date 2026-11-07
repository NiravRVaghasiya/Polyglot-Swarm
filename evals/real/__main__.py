"""CLI for the real-model evaluation (separate from the offline ``python -m evals``).

    python -m evals.real build-datasets
    python -m evals.real validate
    python -m evals.real probe ollama:llama3.1:latest claude
    python -m evals.real run --providers ollama:llama3.1:latest --config default
    python -m evals.real report <run_id>
    python -m evals.real calibrate <dev_run_id>
    python -m evals.real compare <base_run_id> <candidate_run_id>
    python -m evals.real history

Nothing here runs in normal CI. ``run`` makes real, possibly billed, model
calls; a provider that is unavailable is reported as such, never replaced.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from evals.real import providers as prov
from evals.real.config import EvalConfig


def _say(msg: str) -> None:
    print(msg, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.real")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build-datasets", help="regenerate split files + manifests from source.yaml")
    sub.add_parser("validate", help="validate datasets: schema, checksums, leakage")
    p_probe = sub.add_parser("probe", help="check which providers can be evaluated")
    p_probe.add_argument("specs", nargs="+")
    p_run = sub.add_parser("run", help="run the benchmark against real providers")
    p_run.add_argument("--providers", required=True, help="comma-separated provider[:model]")
    p_run.add_argument("--config", default="default")
    p_run.add_argument("--run-id", default=None, help="resume / name a run")
    p_run.add_argument("--limit", type=int, default=None, help="only the first N calls (smoke)")
    p_run.add_argument("--allow-synthetic", action="store_true")
    p_run.add_argument("--timeout", type=float, default=None, help="per-call timeout (s)")
    p_run.add_argument("--max-retries", type=int, default=None)
    p_rep = sub.add_parser("report", help="score a run and write report.json/report.md")
    p_rep.add_argument("run_id")
    p_rep.add_argument("--no-history", action="store_true")
    p_cal = sub.add_parser("calibrate", help="fit per-model calibration maps from a dev-split run")
    p_cal.add_argument("run_id")
    p_cal.add_argument("--out", type=Path, default=None, help="map directory")
    p_cmp = sub.add_parser("compare", help="detect regressions between two runs")
    p_cmp.add_argument("base")
    p_cmp.add_argument("candidate")
    sub.add_parser("history", help="list recorded evaluation results")
    args = parser.parse_args(argv)

    if args.cmd == "build-datasets":
        from evals.real.datasets import TASKS, build_dataset

        for task in TASKS:
            _say(f"wrote {build_dataset(task)}")
        return 0
    if args.cmd == "validate":
        from evals.real.datasets import TASKS, leakage_report, load_manifest, load_split

        ok = True
        for task in TASKS:
            m = load_manifest(task)
            for split in ("dev", "test"):
                load_split(task, split)
            leaks = leakage_report(task)
            bad = {k: v for k, v in leaks.items() if v}
            ok = ok and not bad
            _say(
                f"{task} {m.version}: {m.counts} {m.validation_status_counts} "
                f"leakage={bad or 'none'}"
            )
        return 0 if ok else 1
    if args.cmd == "probe":

        async def _probe() -> None:
            for spec in args.specs:
                result = await prov.probe(prov.parse_spec(spec))
                _say(json.dumps(result.as_dict()))

        asyncio.run(_probe())
        return 0
    if args.cmd == "run":
        from evals.real.runner import run

        config = EvalConfig.load(args.config)
        overrides: dict[str, object] = {}
        if args.timeout is not None:
            overrides["timeout_s"] = args.timeout
        if args.max_retries is not None:
            overrides["max_retries"] = args.max_retries
        config = config.model_copy(update=overrides)
        specs = [prov.parse_spec(s) for s in args.providers.split(",") if s.strip()]
        run_dir = asyncio.run(
            run(
                config,
                specs,
                run_id=args.run_id,
                allow_synthetic=args.allow_synthetic,
                limit=args.limit,
                progress=_say,
            )
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        _say(f"run {manifest['run_id']}: {manifest['status']} -> {run_dir}")
        return 0 if manifest["status"] != "failed" else 1
    if args.cmd == "report":
        from evals.real.report import write_report
        from evals.real.runner import RUNS_DIR

        out = write_report(RUNS_DIR / args.run_id, record_history=not args.no_history)
        _say(f"wrote {out / 'report.md'}")
        return 0
    if args.cmd == "calibrate":
        from evals.real.calibration import CalibrationSplitError, fit_from_run
        from evals.real.runner import RUNS_DIR
        from src.evaluation.calibration_maps import DEFAULT_DIR

        try:
            paths = fit_from_run(RUNS_DIR / args.run_id, args.out or DEFAULT_DIR)
        except CalibrationSplitError as exc:
            _say(f"refused: {exc}")
            return 2
        for path in paths:
            doc = json.loads(path.read_text(encoding="utf-8"))
            _say(f"{doc['key']}: {doc['status']} (dev n={doc['dev_predictions']}) -> {path}")
        return 0
    if args.cmd == "compare":
        from evals.real.regression import compare_runs
        from evals.real.runner import RUNS_DIR

        result = compare_runs(RUNS_DIR / args.base, RUNS_DIR / args.candidate)
        _say(json.dumps(result, indent=2))
        return (
            1
            if any(r.get("decision") == "regression" for r in result.get("comparisons", []))
            else 0
        )
    if args.cmd == "history":
        from evals.real.regression import HISTORY_PATH

        path = Path(HISTORY_PATH)
        _say(path.read_text(encoding="utf-8") if path.exists() else "(no history yet)")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
