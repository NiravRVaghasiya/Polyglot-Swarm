"""ADR-0031: nullable CEFR with explicit evidence states, per-skill independence."""

from __future__ import annotations

from src.assessment import build_cefr_profile, persist_profile
from src.learner import get_knowledge_model
from src.memory import assessments, user_profile


def _seed(user, skill, assessment, n, *, sessions=1, start=0):
    get_knowledge_model().update_from_events(
        user,
        "Spanish",
        [
            {
                "skill": skill,
                "assessment": assessment,
                "confidence": 0.9,
                "item_id": f"{skill}-{start + i}",
                "session_id": f"s{i % sessions}",
                "difficulty": 0.5,
            }
            for i in range(n)
        ],
    )


class TestNoDefaultLevel:
    def test_new_profile_has_no_seeded_level(self, temp_storage):
        profile = user_profile.load_profile("brand-new")
        assert profile.cefr_by_language == {}
        assert not profile.has_working_level("Spanish")
        # Prompts still get an instructional pitch, which is not stored.
        assert profile.cefr_for("Spanish") == user_profile.DEFAULT_WORKING_LEVEL

    def test_new_learner_profile_is_insufficient(self, temp_storage):
        prof = build_cefr_profile("brand-new", "Spanish")
        assert prof.overall is None
        assert prof.overall_status == "insufficient_evidence"
        assert prof.as_dict()["overall"] is None

    def test_persisted_overall_can_be_null(self, temp_storage):
        persist_profile("brand-new", build_cefr_profile("brand-new", "Spanish"))
        row = assessments.latest_assessment("brand-new", "Spanish")
        assert row is not None
        assert row["cefr"] is None
        assert row["status"] == "insufficient_evidence"


class TestOverallNeedsEnoughEvidence:
    def test_one_assessed_skill_is_not_enough_for_overall(self, temp_storage):
        _seed("u", "vocabulary", "correct", 6)
        prof = build_cefr_profile("u", "Spanish")
        assert prof.skills["vocabulary"].cefr is not None
        assert prof.overall is None  # one skill cannot stand for the learner

    def test_insufficient_skill_does_not_drag_overall_down(self, temp_storage):
        _seed("u", "vocabulary", "correct", 6)
        _seed("u", "reading", "correct", 6)
        _seed("u", "grammar", "incorrect", 1)  # one error: insufficient
        prof = build_cefr_profile("u", "Spanish")
        assert prof.skills["grammar"].status == "insufficient_evidence"
        assert prof.skills["grammar"].cefr is None
        assert "grammar" not in prof.overall_basis
        assert prof.overall is not None
        assert "grammar" in prof.unassessed_skills

    def test_missing_skills_are_unassessed_not_zero(self, temp_storage):
        _seed("u", "vocabulary", "correct", 6)
        _seed("u", "reading", "correct", 6)
        prof = build_cefr_profile("u", "Spanish")
        assert "speaking" not in prof.skills
        assert "speaking" in prof.unassessed_skills
        assert prof.overall not in ("A1", None)

    def test_overall_status_is_weakest_contributor(self, temp_storage):
        _seed("u", "vocabulary", "correct", 20, sessions=3)
        _seed("u", "reading", "correct", 4)
        prof = build_cefr_profile("u", "Spanish")
        assert prof.skills["vocabulary"].status == "estimated"
        assert prof.skills["reading"].status == "provisional"
        assert prof.overall_status == "provisional"


class TestSkillIndependence:
    def test_grammar_evidence_does_not_move_vocabulary(self, temp_storage):
        _seed("u", "vocabulary", "correct", 6)
        before = build_cefr_profile("u", "Spanish").skills["vocabulary"]
        _seed("u", "grammar", "incorrect", 10)
        after = build_cefr_profile("u", "Spanish").skills["vocabulary"]
        assert before.mastery == after.mastery
        assert before.cefr == after.cefr


class TestConfidenceIsNotAProbability:
    def test_fields_are_labelled(self, temp_storage):
        _seed("u", "vocabulary", "correct", 6)
        a = build_cefr_profile("u", "Spanish").as_dict()["skills"]["vocabulary"]
        assert {
            "confidence",
            "confidence_label",
            "uncertainty",
            "mastery_low",
            "mastery_high",
        } <= set(a)
        assert a["confidence_label"] in ("none", "low", "medium", "high")
