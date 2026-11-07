"""Fit and evaluate per-model grammar calibration maps.

- :func:`fit_from_run` fits one map per provider/model from a **dev-split**
  run and writes it to ``evals/real/calibration/`` (``python -m evals.real
  calibrate <dev_run_id>``). A run on any other split is refused.
- :func:`committed_calibration` evaluates a committed map on a **test-split**
  run offline: ECE and false-correction rate before and after calibration,
  from the recorded responses (no model calls). The report includes it.

Maps are documents of :mod:`src.evaluation.calibration_maps`, which the app
loads at run time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.real.metrics import _calibration_pairs, proportion
from evals.real.schema import GrammarCase
from evals.real.scoring import GrammarOutcome, score_grammar
from src.evaluation.calibration import calibration_error
from src.evaluation.calibration_maps import (
    CALIBRATION_VERSION,
    DEFAULT_DIR,
    CalibrationMap,
    fit_map,
    load_map,
    map_filename,
)

#: The production grammar prompt; maps are fitted and applied on it only.
PRODUCTION_PROMPT = "grammar@1"


class CalibrationSplitError(ValueError):
    """A calibration map was about to be fitted on a non-dev run."""


def _run_split(manifest: dict[str, Any]) -> str | None:
    grammar = manifest.get("datasets", {}).get("grammar", {})
    splits = {manifest.get("config", {}).get("split"), grammar.get("split")}
    return splits.pop() if len(splits) == 1 else None


def fit_from_run(run_dir: Path, out_dir: Path = DEFAULT_DIR) -> list[Path]:
    """Fit a map per provider/model from a dev run; returns the files written."""
    from evals.real.report import score_run

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    split = _run_split(manifest)
    if split != "dev":
        raise CalibrationSplitError(
            f"run {manifest.get('run_id')} is on split {split!r}; calibration maps are "
            "fitted on the dev split only, so the test split stays unseen"
        )
    scored = score_run(run_dir)
    cases: dict[str, GrammarCase] = scored["grammar_cases"]
    dataset = manifest["datasets"]["grammar"]
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for (key, prompt), outcomes in sorted(scored["grammar"].items()):
        if prompt != PRODUCTION_PROMPT:
            continue
        pairs, _missing = _calibration_pairs(outcomes, cases, raw=False)
        source = {
            "run_id": manifest["run_id"],
            "split": "dev",
            "dataset_version": dataset["version"],
            "dataset_sha256": dataset["sha256"],
            "prompt": PRODUCTION_PROMPT,
            "config_hash": manifest["config_hash"],
            "confidence": "pipeline (the value _select_errors receives)",
        }
        doc = fit_map(key, pairs, source)
        path = out_dir / map_filename(key)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def map_status(key: str, directory: Path = DEFAULT_DIR) -> str:
    """``fitted``, ``insufficient_dev_data``, ``absent`` or ``invalid``."""
    path = directory / map_filename(key)
    if not path.exists():
        return "absent"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "invalid"
    if not isinstance(doc, dict) or doc.get("calibration_version") != CALIBRATION_VERSION:
        return "invalid"
    return str(doc.get("status", "invalid"))


def _fcr(outcomes: list[GrammarOutcome], cases: dict[str, GrammarCase]) -> dict[str, Any]:
    """Detection rates, defined as in :func:`evals.real.metrics.grammar_metrics`."""
    labeled = [o for o in outcomes if o.ok and cases[o.case_id].has_error is not None]
    tp = sum(1 for o in labeled if cases[o.case_id].has_error and o.predicted_error)
    fn = sum(1 for o in labeled if cases[o.case_id].has_error and not o.predicted_error)
    fp = sum(1 for o in labeled if not cases[o.case_id].has_error and o.predicted_error)
    tn = sum(1 for o in labeled if not cases[o.case_id].has_error and not o.predicted_error)
    return {
        "false_correction_rate": proportion(fp, fp + tn),
        "precision": proportion(tp, tp + fp),
        "recall": proportion(tp, tp + fn),
    }


def committed_calibration(
    key: str,
    records: list[dict[str, Any]],
    outcomes: list[GrammarOutcome],
    cases: dict[str, GrammarCase],
    *,
    split: str | None,
    dataset_version: str | None,
    directory: Path = DEFAULT_DIR,
) -> dict[str, Any]:
    """Before/after effect of the committed map for ``key`` on a test run."""
    status = map_status(key, directory)
    if status != "fitted":
        return {"status": status}
    if split != "test":
        return {"status": "not_evaluated", "reason": f"run is on split {split!r}, not test"}
    cal = load_map(key, directory)
    if cal is None:
        return {"status": "invalid"}
    rescored = [
        score_grammar(cases[r["case_id"]], r, model_key=key, calibration_dir=directory)
        for r in records
        if r["task"] == "grammar"
        and r["prompt"] == PRODUCTION_PROMPT
        and f"{r['provider']}:{r['model']}" == key
        and r["case_id"] in cases
    ]
    pairs, _missing = _calibration_pairs(outcomes, cases, raw=False)
    return {
        "status": "evaluated_on_test",
        "map": _describe(cal),
        "dataset_matches": cal.source.get("dataset_version") == dataset_version,
        "test_predictions": len(pairs),
        "ece_before": round(calibration_error(pairs), 4) if pairs else None,
        "ece_after": round(calibration_error([(cal(c), y) for c, y in pairs]), 4)
        if pairs
        else None,
        "before": _fcr(outcomes, cases),
        "after": _fcr(rescored, cases),
    }


def _describe(cal: CalibrationMap) -> dict[str, Any]:
    return {
        "method": cal.method,
        "params": cal.params,
        "dev_predictions": cal.n,
        "source_run": cal.source.get("run_id"),
        "source_split": cal.source.get("split"),
        "dataset_version": cal.source.get("dataset_version"),
    }
