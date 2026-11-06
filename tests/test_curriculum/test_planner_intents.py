"""ADR-0031: the planner separates assessment, remediation, reinforcement and
advancement, and never mistakes missing evidence for weakness."""

from __future__ import annotations

from src.curriculum import ActionIntent, ActionType, PlanConstraints, plan_next_actions
from src.curriculum.planner import MAX_ASSESSMENT_ACTIONS, classify_skill
from src.learner import get_knowledge_model
from src.memory import analytics, vocabulary_db

_ROOMY = PlanConstraints(time_available_minutes=120, max_actions=20)


def _seed(user, skill, assessment, n, *, sessions=1, prefix=""):
    get_knowledge_model().update_from_events(
        user,
        "Spanish",
        [
            {
                "skill": skill,
                "assessment": assessment,
                "confidence": 0.9,
                "item_id": f"{prefix}{skill}-{i}",
                "session_id": f"s{i % sessions}",
                "difficulty": 0.5,
            }
            for i in range(n)
        ],
    )


def _by_skill(plan):
    out = {}
    for a in plan:
        if a.skill and a.target == a.skill:
            out[a.skill] = a
    return out


class TestNewLearner:
    def test_new_learner_gets_assessment_not_remediation(self, temp_storage):
        plan = plan_next_actions("newbie", "Spanish", constraints=_ROOMY)
        intents = {a.intent for a in plan}
        assert ActionIntent.REMEDIATION.value not in intents
        assert ActionIntent.ASSESSMENT.value in intents
        assert any(a.type == ActionType.CONTINUE_CONVERSATION for a in plan)
        for a in plan:
            if a.intent == ActionIntent.ASSESSMENT.value and a.skill:
                assert "weakness" not in a.reason

    def test_unassessed_prerequisites_do_not_block(self, temp_storage):
        # speaking needs vocabulary + grammar, neither assessed yet.
        plan = plan_next_actions("newbie", "Spanish", constraints=_ROOMY)
        assert "speaking" in _by_skill(plan)

    def test_grammar_coverage_drives_a_diagnostic(self, temp_storage):
        plan = plan_next_actions("newbie", "Spanish", constraints=_ROOMY)
        diag = [a for a in plan if a.type == ActionType.DIAGNOSTIC_CHECK]
        assert diag and diag[0].intent == ActionIntent.ASSESSMENT.value
        assert diag[0].target == "gender_agreement"  # easiest unassessed (A1)


class TestInsufficientVsWeak:
    def test_single_error_is_assessment(self, temp_storage):
        _seed("u", "writing", "incorrect", 1)
        writing = _by_skill(plan_next_actions("u", "Spanish", constraints=_ROOMY)).get("writing")
        assert writing is not None
        assert writing.intent == ActionIntent.ASSESSMENT.value

    def test_repeated_identical_error_is_still_assessment(self, temp_storage):
        get_knowledge_model().update_from_events(
            "u",
            "Spanish",
            [{"skill": "writing", "assessment": "incorrect", "confidence": 0.9}] * 10,
        )
        writing = _by_skill(plan_next_actions("u", "Spanish", constraints=_ROOMY))["writing"]
        assert writing.intent == ActionIntent.ASSESSMENT.value

    def test_independent_errors_are_remediation(self, temp_storage):
        _seed("u", "writing", "incorrect", 6)
        writing = _by_skill(plan_next_actions("u", "Spanish", constraints=_ROOMY))["writing"]
        assert writing.intent == ActionIntent.REMEDIATION.value
        assert "weakness" in writing.reason

    def test_single_grammar_flag_is_assessment_recurring_is_remediation(self, temp_storage):
        analytics.record_error("u", "Spanish", "por_vs_para")
        for _ in range(3):
            analytics.record_error("u", "Spanish", "ser_vs_estar")
        plan = plan_next_actions("u", "Spanish", constraints=_ROOMY)
        by_target = {a.target: a for a in plan if a.skill == "grammar"}
        assert by_target["por_vs_para"].intent == ActionIntent.ASSESSMENT.value
        assert by_target["ser_vs_estar"].intent == ActionIntent.REMEDIATION.value


class TestReinforcementAndAdvancement:
    def test_strong_estimated_skill_advances(self, temp_storage):
        _seed("u", "reading", "correct", 20, sessions=3)
        reading = _by_skill(plan_next_actions("u", "Spanish", constraints=_ROOMY))["reading"]
        assert reading.intent == ActionIntent.ADVANCEMENT.value

    def test_mid_skill_is_reinforced(self, temp_storage):
        _seed("u", "reading", "correct", 6, prefix="a")
        _seed("u", "reading", "incorrect", 5, prefix="b")
        reading = _by_skill(plan_next_actions("u", "Spanish", constraints=_ROOMY))["reading"]
        assert reading.intent == ActionIntent.REINFORCEMENT.value

    def test_due_reviews_are_reinforcement_and_keep_fsrs_order(self, temp_storage):
        vocabulary_db.upsert_word("u", "Spanish", "mesa", next_review="2020-01-01T00:00:00+00:00")
        vocabulary_db.upsert_word("u", "Spanish", "silla", next_review="2021-01-01T00:00:00+00:00")
        plan = plan_next_actions("u", "Spanish", constraints=_ROOMY)
        reviews = [a for a in plan if a.type == ActionType.REVIEW_VOCAB]
        assert [a.target for a in reviews] == ["mesa", "silla"]  # most overdue first
        assert all(a.intent == ActionIntent.REINFORCEMENT.value for a in reviews)


class TestPrerequisitesAndCaps:
    def test_demonstrated_weak_prerequisite_blocks(self, temp_storage):
        _seed("u", "vocabulary", "incorrect", 6)
        plan = plan_next_actions("u", "Spanish", constraints=_ROOMY)
        skills = _by_skill(plan)
        assert "reading" not in skills and "listening" not in skills
        assert skills["vocabulary"].intent == ActionIntent.REMEDIATION.value

    def test_assessments_capped_while_learning_actions_exist(self, temp_storage):
        for i in range(4):
            vocabulary_db.upsert_word(
                "u", "Spanish", f"w{i}", next_review="2020-01-01T00:00:00+00:00"
            )
        plan = plan_next_actions("u", "Spanish")  # default 15-minute budget
        assessments = [a for a in plan if a.intent == ActionIntent.ASSESSMENT.value]
        assert len(assessments) <= MAX_ASSESSMENT_ACTIONS

    def test_no_redundant_vocab_assessment_when_reviews_due(self, temp_storage):
        vocabulary_db.upsert_word("u", "Spanish", "mesa", next_review="2020-01-01T00:00:00+00:00")
        plan = plan_next_actions("u", "Spanish", constraints=_ROOMY)
        assert not any(
            a.type == ActionType.RETRIEVAL_PRACTICE and a.intent == ActionIntent.ASSESSMENT.value
            for a in plan
        )

    def test_spare_time_is_filled_with_deferred_assessments(self, temp_storage):
        plan = plan_next_actions("newbie", "Spanish", constraints=_ROOMY)
        assessments = [a for a in plan if a.intent == ActionIntent.ASSESSMENT.value]
        assert len(assessments) > MAX_ASSESSMENT_ACTIONS


class TestClassify:
    def test_none_is_assessment(self):
        assert classify_skill(None) == ActionIntent.ASSESSMENT


class TestGrammarWithoutErrorPatterns:
    def test_weak_grammar_evidence_gets_remediation(self, temp_storage):
        # Graded grammar evidence recorded directly (no analytics error rows).
        get_knowledge_model().update_from_events(
            "u",
            "Spanish",
            [
                {
                    "skill": "grammar",
                    "assessment": "incorrect",
                    "confidence": 0.9,
                    "item_id": c,
                    "objective_id": f"grammar.{c}",
                }
                for c in ("ser_vs_estar", "por_vs_para", "gender_agreement", "subjunctive_present")
            ],
        )
        plan = plan_next_actions("u", "Spanish", constraints=_ROOMY)
        grammar = [a for a in plan if a.skill == "grammar"]
        assert grammar
        assert all(a.intent == ActionIntent.REMEDIATION.value for a in grammar)
        assert {a.target for a in grammar} <= {
            "ser_vs_estar",
            "por_vs_para",
            "gender_agreement",
            "subjunctive_present",
        }
