"""Phase 6 tests: mastery engine, uncertainty, skill graph, knowledge model,
and the persist_session integration."""

from __future__ import annotations

from src.learner import KnowledgeModel, MasteryEngine, SkillBelief, skill_graph, uncertainty


def _events(skill, assessment, n, confidence=0.9):
    return [{"skill": skill, "assessment": assessment, "confidence": confidence} for _ in range(n)]


class TestUncertainty:
    def test_no_evidence_is_max_uncertainty(self):
        assert uncertainty.uncertainty_from_evidence(0) == 1.0

    def test_uncertainty_shrinks_with_evidence(self):
        u1 = uncertainty.uncertainty_from_evidence(2)
        u2 = uncertainty.uncertainty_from_evidence(10)
        assert u2 < u1 < 1.0

    def test_blend_weight_decreases_with_prior_evidence(self):
        early = uncertainty.blend_weight(0, 1.0)
        late = uncertainty.blend_weight(10, 1.0)
        assert early > late

    def test_wilson_interval_bounds(self):
        low, high = uncertainty.wilson_interval(8, 10)
        assert 0.0 <= low <= high <= 1.0
        assert uncertainty.wilson_interval(0, 0) == (0.0, 1.0)


class TestMasteryEngine:
    def test_correct_evidence_raises_mastery(self):
        eng = MasteryEngine()
        post = eng.update_skill(
            SkillBelief(skill="vocabulary", mastery=0.3), _events("vocabulary", "correct", 4)
        )
        assert post.mastery > 0.3

    def test_incorrect_evidence_lowers_mastery(self):
        eng = MasteryEngine()
        post = eng.update_skill(
            SkillBelief(skill="grammar", mastery=0.8, sample_size=2),
            _events("grammar", "incorrect", 3),
        )
        assert post.mastery < 0.8

    def test_uncertainty_shrinks_with_more_events(self):
        eng = MasteryEngine()
        post = eng.update_skill(SkillBelief(skill="grammar"), _events("grammar", "incorrect", 5))
        assert post.uncertainty < 1.0
        assert post.sample_size > 0

    def test_acceptable_variation_not_punished(self):
        eng = MasteryEngine()
        post = eng.update_skill(
            SkillBelief(skill="grammar", mastery=0.7, sample_size=3),
            [{"skill": "grammar", "assessment": "regional", "confidence": 0.8}],
        )
        # A regional/acceptable observation must not tank mastery.
        assert post.mastery >= 0.6

    def test_unmappable_assessment_ignored(self):
        eng = MasteryEngine()
        prior = SkillBelief(skill="grammar", mastery=0.5, sample_size=2)
        post = eng.update_skill(
            prior, [{"skill": "grammar", "assessment": "???", "confidence": 1.0}]
        )
        assert post.mastery == 0.5  # unchanged

    def test_update_from_events_groups_by_skill(self):
        eng = MasteryEngine()
        events = [
            {"skill": "grammar", "assessment": "incorrect", "confidence": 0.9},
            {"skill": "vocabulary", "assessment": "observed", "confidence": 0.8},
            {"skill": None, "assessment": None, "confidence": 1.0},  # ignored
        ]
        result = eng.update_from_events({}, events)
        assert set(result) == {"grammar", "vocabulary"}

    def test_mastery_stays_in_range(self):
        eng = MasteryEngine()
        post = eng.update_skill(
            SkillBelief(skill="vocabulary"), _events("vocabulary", "correct", 50)
        )
        assert 0.0 <= post.mastery <= 1.0
        assert 0.0 <= post.uncertainty <= 1.0


class TestSkillGraph:
    def test_grammar_has_no_prerequisites(self):
        assert skill_graph.skill_prerequisites("grammar") == ()

    def test_speaking_depends_on_vocab_and_grammar(self):
        prereqs = skill_graph.skill_prerequisites("speaking")
        assert "vocabulary" in prereqs and "grammar" in prereqs

    def test_readiness(self):
        assert skill_graph.is_ready("grammar", {})  # no prereqs
        assert not skill_graph.is_ready("speaking", {"vocabulary": 0.1, "grammar": 0.1})
        assert skill_graph.is_ready("speaking", {"vocabulary": 0.6, "grammar": 0.6})

    def test_unmet_prerequisites(self):
        unmet = skill_graph.unmet_prerequisites("writing", {"vocabulary": 0.6, "grammar": 0.1})
        assert "grammar" in unmet
        assert "vocabulary" not in unmet

    def test_construction_prerequisites_from_pack(self):
        prereqs = skill_graph.construction_prerequisites("Spanish", "preterite_vs_imperfect")
        assert "gender_agreement" in prereqs


class TestKnowledgeModel:
    def test_update_persists_skill_states(self, temp_storage):
        km = KnowledgeModel()
        events = [
            {"skill": "grammar", "assessment": "incorrect", "confidence": 0.9},
            {"skill": "vocabulary", "assessment": "observed", "confidence": 0.8},
        ]
        km.update_from_events("u1", "Spanish", events)
        beliefs = km.current_beliefs("u1", "Spanish")
        assert "grammar" in beliefs and "vocabulary" in beliefs

    def test_beliefs_accumulate_across_updates(self, temp_storage):
        km = KnowledgeModel()
        km.update_from_events("u1", "Spanish", _events("vocabulary", "correct", 2))
        first = km.current_beliefs("u1", "Spanish")["vocabulary"]
        km.update_from_events("u1", "Spanish", _events("vocabulary", "correct", 2))
        second = km.current_beliefs("u1", "Spanish")["vocabulary"]
        assert second.sample_size > first.sample_size
        assert second.uncertainty <= first.uncertainty

    def test_snapshot_written(self, temp_storage):
        km = KnowledgeModel()
        km.update_from_events("u1", "Spanish", _events("grammar", "incorrect", 2))
        row_id = km.snapshot("u1", "Spanish", reason="test")
        assert row_id > 0
        from src.memory.db import get_connection

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM learner_state_snapshots WHERE id=?", (row_id,)
            ).fetchone()
        assert row["reason"] == "test"

    def test_mastery_by_skill(self, temp_storage):
        km = KnowledgeModel()
        km.update_from_events("u1", "Spanish", _events("vocabulary", "correct", 3))
        m = km.mastery_by_skill("u1", "Spanish")
        assert "vocabulary" in m
        assert 0.0 <= m["vocabulary"] <= 1.0


class TestPersistSessionUpdatesModel:
    def test_session_updates_skill_beliefs(self, temp_storage):
        from src.memory import skill_state
        from src.orchestrator.lifecycle import build_initial_state, persist_session

        state = build_initial_state("learner", "Spanish", session_id="sess-p6")
        state["messages"] = [{"role": "user", "content": "Yo soy hambre"}]
        state["grammar_errors"] = [
            {
                "original": "Yo soy hambre",
                "correction": "Yo tengo hambre",
                "rule": "ser_vs_tener",
                "construction": "ser_vs_tener",
                "classification": "wrong",
                "severity": "critical",
                "confidence": 0.9,
            }
        ]
        state["new_vocabulary"] = [{"word": "hambre", "translation": "hunger", "pos": "noun"}]

        persist_session(state)

        skills = skill_state.get_skills("learner", "Spanish")
        # The session produced grammar (error) and vocabulary (produced) evidence.
        assert "grammar" in skills
        assert "vocabulary" in skills
        assert skills["grammar"]["uncertainty"] < 1.0  # evidence reduced uncertainty
