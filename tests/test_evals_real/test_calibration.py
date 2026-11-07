"""Calibration maps are fitted on dev runs only, and the committed ones say so."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.real import calibration
from evals.real.runner import RUNS_DIR
from src.evaluation import calibration_maps as cm

COMMITTED = sorted(cm.DEFAULT_DIR.glob("*.json"))


def test_fitting_on_a_test_split_run_is_refused(tmp_path):
    with pytest.raises(calibration.CalibrationSplitError, match="dev split only"):
        calibration.fit_from_run(RUNS_DIR / "20261106-local-test", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_maps_for_the_evaluated_local_models_are_committed():
    keys = {json.loads(p.read_text(encoding="utf-8"))["key"] for p in COMMITTED}
    assert {"ollama:llama3.1:latest", "ollama:gemma2:2b"} <= keys


@pytest.mark.parametrize("path", COMMITTED, ids=[p.name for p in COMMITTED])
def test_committed_maps_come_from_dev_runs(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["calibration_version"] == cm.CALIBRATION_VERSION
    assert path.name == cm.map_filename(doc["key"])
    source = doc["source"]
    assert source["split"] == "dev"
    manifest = json.loads((RUNS_DIR / source["run_id"] / "manifest.json").read_text("utf-8"))
    assert manifest["config"]["split"] == "dev"
    grammar = manifest["datasets"]["grammar"]
    assert (grammar["split"], grammar["version"], grammar["sha256"]) == (
        "dev",
        source["dataset_version"],
        source["dataset_sha256"],
    )


def test_committed_maps_are_reproducible_from_their_dev_run(tmp_path):
    runs = {json.loads(p.read_text(encoding="utf-8"))["source"]["run_id"] for p in COMMITTED}
    for run_id in runs:
        calibration.fit_from_run(RUNS_DIR / run_id, tmp_path)
    for path in COMMITTED:
        assert (tmp_path / path.name).read_text(encoding="utf-8") == path.read_text(
            encoding="utf-8"
        )


def test_test_run_report_states_before_and_after():
    report = json.loads(
        (RUNS_DIR / "20261106-local-test" / "report.json").read_text(encoding="utf-8")
    )
    providers = report["providers"]
    gemma = providers["ollama:gemma2:2b"]["committed_calibration"]
    assert gemma["status"] == "evaluated_on_test"
    assert gemma["map"]["source_split"] == "dev"
    for side in ("before", "after"):
        assert gemma[side]["false_correction_rate"]["denominator"] > 0
    assert gemma["ece_before"] is not None and gemma["ece_after"] is not None
    assert (
        gemma["before"]["false_correction_rate"]
        == providers["ollama:gemma2:2b"]["grammar"]["false_correction_rate"]
    )
    llama = providers["ollama:llama3.1:latest"]["committed_calibration"]
    assert llama["status"] == cm.INSUFFICIENT
