"""Tests for the published-results artifact generator (Gate C).

Verifies the generator runs all three harnesses and renders a markdown
artifact with real measured numbers plus the known-limitations section, and
that it refuses to run outside deterministic mode (the reproducibility
guarantee).
"""

from __future__ import annotations

import pytest

from src.experiments import results as results_mod


class TestGenerate:
    async def test_writes_artifact_with_all_sections(self, tmp_path):
        out = tmp_path / "results.md"
        markdown = await results_mod.generate(output=out, learners_per_arm=1)

        assert out.exists()
        written = out.read_text(encoding="utf-8")
        assert written == markdown

        # Every major section is present.
        assert "# Measured results" in markdown
        assert "## Component benchmarks" in markdown
        assert "## Evaluation suites" in markdown
        assert "## Ablation study" in markdown
        assert "## Known limitations" in markdown
        assert "## Reproduce" in markdown

    async def test_ablation_arms_appear_with_gain_direction(self, tmp_path):
        markdown = await results_mod.generate(output=tmp_path / "r.md", learners_per_arm=1)
        # The analysis arms (D/E) show a positive gain and the others none; the
        # artifact renders it. (The exact value depends on the learner-model
        # engine — it was +0.333 under the pre-ADR-0031 engine — so the test
        # checks the direction, which is what the ablation is about.)
        gains = {}
        for line in markdown.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 6 and cells[0] in ("A", "B", "C", "D", "E"):
                gains[cells[0]] = float(cells[5])
        assert set(gains) == {"A", "B", "C", "D", "E"}
        assert gains["D"] > 0 and gains["E"] > 0
        assert gains["A"] == gains["B"] == gains["C"] == 0.0

    async def test_stdout_only_does_not_write(self, tmp_path):
        out = tmp_path / "nope.md"
        await results_mod.generate(output=out, learners_per_arm=1, write=False)
        assert not out.exists()

    async def test_refuses_without_deterministic_mode(self, tmp_path, monkeypatch):
        monkeypatch.delenv("POLYGLOT_DETERMINISTIC", raising=False)
        with pytest.raises(RuntimeError, match="deterministic"):
            await results_mod.generate(output=tmp_path / "r.md")


class TestCollectResults:
    async def test_collects_structured_data(self):
        data = await results_mod.collect_results(learners_per_arm=1)
        assert data["deterministic"] is True
        assert data["benchmarks"]  # non-empty
        assert data["evals"]
        assert data["ablation"]["arms"]
        # Benchmarks carry measured metrics, not just pass/fail.
        assert any(b["metrics"] for b in data["benchmarks"])
