"""Phase 12 tests: multidimensional CEFR profile + assessment_node upgrade."""

from __future__ import annotations

from src.assessment import (
    build_cefr_profile,
    mastery_to_cefr,
    persist_profile,
)
from src.assessment.cefr_profile import confidence_from
from src.learner import get_knowledge_model
from src.memory import assessments


def _seed_skill(user, language, skill, assessment, n, confidence=0.9):
    get_knowledge_model().update_from_events(
        user,
        language,
        [{"skill": skill, "assessment": assessment, "confidence": confidence} for _ in range(n)],
    )


class TestMasteryToCEFR:
    def test_monotonic_bands(self):
        assert mastery_to_cefr(0.05) == "A1"
        assert mastery_to_cefr(0.3) == "A2"
        assert mastery_to_cefr(0.5) == "B1"
        assert mastery_to_cefr(0.7) == "B2"
        assert mastery_to_cefr(0.85) == "C1"
        assert mastery_to_cefr(0.99) == "C2"

    def test_clamped(self):
        assert mastery_to_cefr(-1.0) == "A1"
        assert mastery_to_cefr(2.0) == "C2"


class TestConfidence:
    def test_no_evidence_low_confidence(self):
        assert confidence_from(uncertainty=1.0, sample_size=0) < 0.1

    def test_more_evidence_raises_confidence(self):
        low = confidence_from(uncertainty=0.5, sample_size=2)
        high = confidence_from(uncertainty=0.5, sample_size=40)
        assert high > low

    def test_lower_uncertainty_raises_confidence(self):
        assert confidence_from(0.1, 10) > confidence_from(0.9, 10)


class TestBuildProfile:
    def test_empty_learner_no_skills(self, temp_storage):
        prof = build_cefr_profile("newbie", "Spanish", fallback_cefr="A2")
        assert prof.skills == {}
        assert prof.overall == "A2"  # fallback

    def test_per_skill_bands(self, temp_storage):
        _seed_skill("u1", "Spanish", "vocabulary", "correct", 8)
        _seed_skill("u1", "Spanish", "grammar", "incorrect", 3)
        prof = build_cefr_profile("u1", "Spanish")
        assert "vocabulary" in prof.skills and "grammar" in prof.skills
        # Strong vocab -> high band; failing grammar -> A1.
        assert prof.skills["vocabulary"].cefr in ("C1", "C2")
        assert prof.skills["grammar"].cefr == "A1"

    def test_overall_is_conservative_min(self, temp_storage):
        _seed_skill("u1", "Spanish", "vocabulary", "correct", 8)
        _seed_skill("u1", "Spanish", "grammar", "incorrect", 3)
        prof = build_cefr_profile("u1", "Spanish")
        assert prof.overall == "A1"  # min across skills

    def test_confidence_and_sample_size_present(self, temp_storage):
        _seed_skill("u1", "Spanish", "vocabulary", "correct", 6)
        prof = build_cefr_profile("u1", "Spanish")
        a = prof.skills["vocabulary"]
        assert 0.0 <= a.confidence <= 1.0
        assert a.sample_size > 0

    def test_as_dict(self, temp_storage):
        _seed_skill("u1", "Spanish", "vocabulary", "correct", 4)
        d = build_cefr_profile("u1", "Spanish").as_dict()
        assert d["language"] == "Spanish"
        assert "overall" in d and "skills" in d


class TestPersistProfile:
    def test_writes_per_skill_and_overall_rows(self, temp_storage):
        _seed_skill("u1", "Spanish", "vocabulary", "correct", 6)
        _seed_skill("u1", "Spanish", "grammar", "incorrect", 3)
        prof = build_cefr_profile("u1", "Spanish")
        written = persist_profile("u1", prof)
        # 2 skills + 1 overall.
        assert written == 3

        vocab = assessments.latest_assessment("u1", "Spanish", skill="vocabulary")
        assert vocab is not None
        assert vocab["method"] == "cefr-profile-v1"
        assert vocab["sample_size"] > 0

        overall = assessments.latest_assessment("u1", "Spanish")  # skill=None
        assert overall is not None
        assert overall["cefr"] == prof.overall


class TestAssessmentNodeUpgrade:
    async def test_returns_cefr_level_and_persists_profile(self, temp_storage, monkeypatch):
        from src.agents import assessment
        from src.memory import user_profile, vocabulary_db

        # Give the learner vocab breadth + skill beliefs.
        for i in range(1200):
            vocabulary_db.upsert_word("u3", "Spanish", f"w{i}")
        _seed_skill("u3", "Spanish", "vocabulary", "correct", 6)

        state = {
            "user_id": "u3",
            "language": "Spanish",
            "cefr_level": "A2",
            "messages": [
                {"role": "user", "content": " ".join(["palabra"] * 20)}  # long-ish turn
            ],
            "grammar_errors": [],
        }
        result = await assessment.assessment_node(state)

        # Legacy contract preserved: returns {cefr_level} + updates profile.
        assert "cefr_level" in result
        assert user_profile.load_profile("u3").cefr_for("Spanish") == result["cefr_level"]

        # Phase 12 addition: the multidimensional profile was persisted.
        history = assessments.assessment_history("u3", "Spanish")
        assert any(row["method"] == "cefr-profile-v1" for row in history)
        assert any(row["skill"] == "vocabulary" for row in history)


class TestAssessCLI:
    def test_assess_command_runs(self, temp_storage):
        from typer.testing import CliRunner

        from src.cli import app

        _seed_skill("cli-user", "Spanish", "vocabulary", "correct", 4)
        result = CliRunner().invoke(app, ["assess", "--language", "Spanish"])
        assert result.exit_code == 0
        assert "CEFR profile" in result.stdout
