"""CLI: ``python -m evals.adaptive <command>`` — SIMULATED evaluations only.

Commands:
  models    held-out learner-model comparison (Checkpoint 1)
  policies  baseline vs adaptive planner outcome simulation (Checkpoint 6)

Results are written to ``evals/adaptive/results/<name>.json`` and ``.md``.
Every report states that its learners are simulated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"


def _write(name: str, data: dict[str, Any], markdown: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(
        json.dumps(data, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    path = RESULTS_DIR / f"{name}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.adaptive")
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("models", help="held-out learner-model comparison")
    m.add_argument("--family", default="continuous", choices=["continuous", "bkt"])
    m.add_argument("--train", type=int, default=40)
    m.add_argument("--test", type=int, default=60)
    m.add_argument("--bootstrap", type=int, default=1000)
    m.add_argument(
        "--logs",
        default=None,
        help="JSONL of REAL evidence rows (e.g. a privacy export); learners split by hash",
    )
    p = sub.add_parser("policies", help="planner outcome simulation")
    p.add_argument("--learners", type=int, default=40)
    p.add_argument("--sessions", type=int, default=20)
    p.add_argument("--gain-peak", default="0.7", help="float, or 'flat'")
    p.add_argument("--family", default="continuous", choices=["continuous", "bkt"])
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--name", default=None)
    args = parser.parse_args(argv)

    if args.command == "models" and args.logs:
        from evals.adaptive.model_eval import compare, split_real_logs
        from evals.adaptive.report import render_models

        rows = [
            json.loads(line)
            for line in Path(args.logs).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        train, test = split_real_logs(rows)
        data = compare(
            train, test, simulated=False, meta={"source": args.logs}, samples=args.bootstrap, seed=1
        )
        path = _write("models-real", data, render_models(data))
        print(f"wrote {path}")
        return 0
    if args.command == "models":
        from evals.adaptive.model_eval import ModelEvalConfig, evaluate
        from evals.adaptive.report import render_models

        cfg = ModelEvalConfig(
            family=args.family,
            n_train=args.train,
            n_test=args.test,
            bootstrap_samples=args.bootstrap,
        )
        data = evaluate(cfg)
        path = _write(f"models-{args.family}", data, render_models(data))
        print(f"wrote {path}")
        return 0
    if args.command == "policies":
        from evals.adaptive.policy_eval import PolicyEvalConfig, evaluate_policies
        from evals.adaptive.report import render_policies

        peak = None if args.gain_peak == "flat" else float(args.gain_peak)
        pcfg = PolicyEvalConfig(
            n_learners=args.learners,
            n_sessions=args.sessions,
            gain_peak=peak,
            family=args.family,
            bootstrap_samples=args.bootstrap,
        )
        data = evaluate_policies(pcfg)
        name = args.name or f"policies-{args.family}-peak-{args.gain_peak}"
        path = _write(name, data, render_policies(data))
        print(f"wrote {path}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
