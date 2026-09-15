"""Tests for the ablation study runner (Gate C: the execution harness).

Proves the harness actually joins the ablation graph builder to the outcomes
store and produces a *sensitive* controlled comparison — arms that run the
analysis pipeline (D/E) accumulate measurable learner-model mastery, while
conversation-only arms (A/B/C) do not.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.experiments import run_ablation_study, summarize_report
from src.experiments.runner import ABLATION_EXPERIMENT, METRIC
from src.memory import experiments


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", str(data_dir), raising=False)
    monkeypatch.setattr(settings, "profiles_dir", str(data_dir / "profiles"), raising=False)
    monkeypatch.setattr(settings, "db_path", str(data_dir / "polyglot.db"), raising=False)
    monkeypatch.setattr(settings, "chroma_path", str(data_dir / "chroma"), raising=False)
    return data_dir


class TestRunAblationStudy:
    async def test_runs_all_arms_and_records_outcomes(self, temp_storage):
        report = await run_ablation_study(learners_per_arm=2)

        assert {a.arm for a in report.arms} == {"A", "B", "C", "D", "E"}
        # pre + post recorded for every learner in every arm.
        summary = experiments.summarize_outcomes(ABLATION_EXPERIMENT, METRIC)
        for arm in ("A", "B", "C", "D", "E"):
            assert summary[arm]["pre_test"]["n"] == 2
            assert summary[arm]["immediate_post"]["n"] == 2

    async def test_analysis_arms_gain_and_conversation_only_arms_do_not(self, temp_storage):
        report = await run_ablation_study(learners_per_arm=2)
        by_arm = {a.arm: a for a in report.arms}

        # Conversation-only / review-only arms produce no learner-model evidence.
        assert by_arm["A"].mean_gain == pytest.approx(0.0)
        assert by_arm["B"].mean_gain == pytest.approx(0.0)
        assert by_arm["C"].mean_gain == pytest.approx(0.0)
        # Arms with the analysis pipeline measurably build mastery.
        assert by_arm["D"].mean_gain > 0.0
        assert by_arm["E"].mean_gain > 0.0

    async def test_full_system_gain_matches_analysis_arm(self, temp_storage):
        # E (full) and D (analysis) both include the analysis pipeline; the
        # difference between them is review/FSRS, which doesn't add mastery
        # evidence in this scripted single-session lesson — so their measured
        # gains should be equal, which is itself an informative ablation result.
        report = await run_ablation_study(learners_per_arm=2)
        by_arm = {a.arm: a for a in report.arms}
        assert by_arm["E"].mean_gain == pytest.approx(by_arm["D"].mean_gain)

    async def test_can_restrict_to_a_subset_of_arms(self, temp_storage):
        report = await run_ablation_study(arms=["A", "E"], learners_per_arm=1)
        assert {a.arm for a in report.arms} == {"A", "E"}

    async def test_summarize_report_renders_every_arm(self, temp_storage):
        report = await run_ablation_study(learners_per_arm=1)
        text = summarize_report(report)
        for arm in ("A", "B", "C", "D", "E"):
            assert arm in text
        assert "gain" in text

    async def test_outcome_payload_carries_reference_cefr(self, temp_storage):
        await run_ablation_study(arms=["E"], learners_per_arm=1)
        outcomes = experiments.get_outcomes(ABLATION_EXPERIMENT, measurement_point="immediate_post")
        assert outcomes
        payload = outcomes[0]["payload"]
        assert "overall_cefr" in payload
        assert "per_skill_mastery" in payload
