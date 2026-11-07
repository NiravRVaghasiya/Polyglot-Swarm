"""Opt-in integration tests against real providers.

Skipped unless ``POLYGLOT_REAL_EVAL=1``. Providers come from
``POLYGLOT_REAL_EVAL_PROVIDERS`` (comma-separated ``provider[:model]``,
default ``ollama``). These make real, possibly billed, calls — they never run
in the offline CI job.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from evals.real import providers as prov
from evals.real import runner
from evals.real.config import EvalConfig

pytestmark = [
    pytest.mark.real_model,
    pytest.mark.skipif(
        os.getenv("POLYGLOT_REAL_EVAL") != "1",
        reason="set POLYGLOT_REAL_EVAL=1 to call real providers",
    ),
]

SPECS = [
    prov.parse_spec(s)
    for s in os.getenv("POLYGLOT_REAL_EVAL_PROVIDERS", "ollama").split(",")
    if s.strip()
]


@pytest.mark.parametrize("spec", SPECS, ids=[s.key for s in SPECS])
def test_probe_classifies_without_raising(spec):
    result = asyncio.run(prov.probe(spec, timeout_s=300))
    assert result.status in {
        prov.AVAILABLE,
        prov.NOT_CONFIGURED,
        prov.UNREACHABLE,
        prov.AUTH_FAILED,
        prov.MODEL_NOT_FOUND,
        prov.SDK_MISSING,
        prov.TIMEOUT,
        prov.ERROR,
    }


@pytest.mark.parametrize("spec", SPECS, ids=[s.key for s in SPECS])
def test_one_real_call_is_recorded(spec, tmp_path):
    if asyncio.run(prov.probe(spec, timeout_s=300)).status != prov.AVAILABLE:
        pytest.skip(f"{spec.key} is not available")
    config = EvalConfig(tasks=["grammar"], timeout_s=900, max_retries=1)
    run_dir = asyncio.run(runner.run(config, [spec], run_id="it", runs_dir=tmp_path, limit=1))
    rec = json.loads((run_dir / "responses.jsonl").read_text("utf-8").splitlines()[0])
    assert rec["synthetic"] is False
    assert rec["ok"], rec["errors"]
    assert rec["response_text"]
