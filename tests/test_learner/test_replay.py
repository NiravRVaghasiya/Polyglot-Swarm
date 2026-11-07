"""ADR-0031: provenance, idempotent processing, deterministic replay, supersession."""

from __future__ import annotations

import random

import pytest

from src.evidence import store
from src.evidence.events import EVENT_SCHEMA_VERSION, EventType, LearningEvent
from src.evidence.provenance import Provenance
from src.learner import KnowledgeModel
from src.memory import lkm_history, skill_state
from src.memory.db import get_connection


def _events(user: str, n: int, *, assessment: str = "correct", skill_type=EventType.GRAMMAR_ERROR):
    p = Provenance("test-src", session_id="sess-1", prompt_version="grammar@1")
    return [
        LearningEvent.create(
            EventType.REVIEW_RESULT,
            user,
            "Spanish",
            provenance=p,
            item_id=f"word{i}",
            assessment=assessment,
            confidence=0.95,
            created_at=f"2026-10-01T10:00:{i:02d}+00:00",
        )
        for i in range(n)
    ]


def _dump(events):
    return [e.model_dump() for e in events]


class TestIdempotentProcessing:
    def test_same_events_twice_change_nothing(self, temp_storage):
        km = KnowledgeModel()
        events = _events("u", 5)
        km.update_from_events("u", "Spanish", _dump(events))
        state1 = skill_state.get_skills("u", "Spanish")
        runs1 = lkm_history.list_runs("u", "Spanish")

        km.update_from_events("u", "Spanish", _dump(events))
        km.recompute("u", "Spanish")
        state2 = skill_state.get_skills("u", "Spanish")
        runs2 = lkm_history.list_runs("u", "Spanish")

        assert store.count_events("u", "Spanish") == 5
        assert len(runs1) == len(runs2) == 1  # no new run for unchanged evidence
        assert state1["vocabulary"]["mastery"] == state2["vocabulary"]["mastery"]
        assert state1["vocabulary"]["evidence_digest"] == state2["vocabulary"]["evidence_digest"]

    def test_persist_session_twice_does_not_double_count(self, temp_storage):
        from src.orchestrator.lifecycle import build_initial_state, persist_session

        state = build_initial_state("learner", "Spanish", session_id="sess-twice")
        state["messages"] = [{"role": "user", "content": "Yo soy hambre"}]
        state["grammar_errors"] = [
            {
                "original": "Yo soy hambre",
                "correction": "Yo tengo hambre",
                "construction": "ser_vs_estar",
                "classification": "wrong",
                "severity": "critical",
                "confidence": 0.9,
            }
        ]
        persist_session(state)
        first = KnowledgeModel().current_estimates("learner", "Spanish")["grammar"]
        persist_session(state)  # e.g. a retried finalize
        second = KnowledgeModel().current_estimates("learner", "Spanish")["grammar"]
        assert first.independent_count == second.independent_count == 1
        assert first.mastery == second.mastery


class TestTraceability:
    def test_every_update_names_its_evidence(self, temp_storage):
        km = KnowledgeModel()
        batch1 = _events("u", 3)
        km.update_from_events("u", "Spanish", _dump(batch1))
        batch2 = [
            e.model_copy(update={"event_id": f"b2-{i}", "item_id": f"other{i}"})
            for i, e in enumerate(_events("u", 2, assessment="incorrect"))
        ]
        km.update_from_events("u", "Spanish", _dump(batch2))

        history = km.history("u", "Spanish", skill="vocabulary")
        assert len(history) == 2
        assert set(history[0]["new_event_ids"]) == {e.event_id for e in batch1}
        assert set(history[1]["new_event_ids"]) == {e.event_id for e in batch2}
        assert history[1]["mastery_before"] == pytest.approx(history[0]["mastery_after"])
        assert history[1]["mastery_after"] < history[1]["mastery_before"]
        assert all(h["method"] == "lkm-evidence-v2" for h in history)

    def test_explain_lists_every_event(self, temp_storage):
        km = KnowledgeModel()
        events = _events("u", 3)
        dup = events[0].model_copy(update={"event_id": "dup-0"})
        km.update_from_events("u", "Spanish", _dump([*events, dup]))
        estimate = km.explain("u", "Spanish", "vocabulary")
        assert estimate is not None
        roles = {c.event_id: c.role for c in estimate.contributions}
        assert set(roles) == {e.event_id for e in events} | {"dup-0"}
        assert sorted(roles.values()).count("merged") == 1

    def test_provenance_fields_persisted(self, temp_storage):
        e = LearningEvent.create(
            EventType.GRAMMAR_ERROR,
            "u",
            "Spanish",
            provenance=Provenance(
                "grammar-agent",
                session_id="s",
                model_version="m-1",
                rubric_version="r-1",
                prompt_version="grammar@1",
            ),
            item_id="ser_vs_estar",
            subskill="ser_vs_estar",
            objective_id="grammar.ser_vs_estar",
            task_type="free_conversation",
            difficulty=0.25,
            assessment="incorrect",
        )
        store.record_events([e])
        row = store.get_event(e.event_id)
        assert row is not None
        assert row["model_version"] == "m-1"
        assert row["rubric_version"] == "r-1"
        assert row["prompt_version"] == "grammar@1"
        assert row["objective_id"] == "grammar.ser_vs_estar"
        assert row["difficulty"] == 0.25
        assert row["difficulty_basis"] == "measured"
        assert row["schema_version"] == EVENT_SCHEMA_VERSION
        assert row["fingerprint"] == e.fingerprint()
        assert row["recorded_at"]


class TestDeterministicReplay:
    def test_replay_matches_recompute(self, temp_storage):
        km = KnowledgeModel()
        km.update_from_events("u", "Spanish", _dump(_events("u", 6)))
        live = km.current_estimates("u", "Spanish")
        replayed = km.replay("u", "Spanish")
        assert {s: e.mastery for s, e in live.items()} == {
            s: e.mastery for s, e in replayed.items()
        }
        assert KnowledgeModel.overall_digest(live) == KnowledgeModel.overall_digest(replayed)

    def test_replay_as_of_an_earlier_run(self, temp_storage):
        km = KnowledgeModel()
        km.update_from_events("u", "Spanish", _dump(_events("u", 3)))
        first_run = lkm_history.latest_run("u", "Spanish")
        first = km.current_estimates("u", "Spanish")["vocabulary"].mastery
        more = [
            e.model_copy(update={"event_id": f"x{i}", "item_id": f"x{i}"})
            for i, e in enumerate(_events("u", 4, assessment="incorrect"))
        ]
        km.update_from_events("u", "Spanish", _dump(more))
        assert first_run is not None
        past = km.replay("u", "Spanish", run_id=int(first_run["id"]))["vocabulary"].mastery
        assert past == first
        assert km.current_estimates("u", "Spanish")["vocabulary"].mastery != first

    def test_import_order_does_not_matter(self, temp_storage, tmp_path, monkeypatch):
        from src.config import settings

        events = _events("u", 4) + [
            e.model_copy(update={"event_id": f"n{i}", "item_id": f"n{i}"})
            for i, e in enumerate(_events("u", 3, assessment="incorrect"))
        ]
        KnowledgeModel().update_from_events("u", "Spanish", _dump(events))
        a = KnowledgeModel().current_estimates("u", "Spanish")

        monkeypatch.setattr(settings, "db_path", str(tmp_path / "other.db"), raising=False)
        shuffled = list(events)
        random.Random(3).shuffle(shuffled)
        for e in shuffled:  # one at a time, in a different order
            KnowledgeModel().update_from_events("u", "Spanish", _dump([e]))
        b = KnowledgeModel().current_estimates("u", "Spanish")
        assert a["vocabulary"].mastery == b["vocabulary"].mastery
        assert a["vocabulary"].evidence_digest == b["vocabulary"].evidence_digest


class TestSupersession:
    def test_correction_replaces_evidence_without_editing_it(self, temp_storage):
        km = KnowledgeModel()
        events = _events("u", 4)
        km.update_from_events("u", "Spanish", _dump(events))
        before = km.current_estimates("u", "Spanish")["vocabulary"]

        wrong = events[0]
        fixed = wrong.model_copy(update={"event_id": "fix-0", "assessment": "incorrect"})
        assert store.supersede_event(wrong.event_id, replacement=fixed, reason="regraded")
        after = km.recompute("u", "Spanish", trigger="correction")["vocabulary"]

        assert after.mastery < before.mastery
        assert wrong.event_id not in after.event_ids and "fix-0" in after.event_ids
        original = store.get_event(wrong.event_id)
        assert original is not None and original["assessment"] == "correct"  # untouched
        sup = store.get_supersessions("u")
        assert sup[0]["superseded_event_id"] == wrong.event_id
        assert sup[0]["superseding_event_id"] == "fix-0"
        last = km.history("u", "Spanish", skill="vocabulary")[-1]
        assert wrong.event_id in last["removed_event_ids"]
        assert "fix-0" in last["new_event_ids"]

    def test_supersession_is_idempotent(self, temp_storage):
        km = KnowledgeModel()
        events = _events("u", 3)
        km.update_from_events("u", "Spanish", _dump(events))
        assert store.supersede_event(events[1].event_id, reason="retracted")
        assert not store.supersede_event(events[1].event_id, reason="retracted")
        km.recompute("u", "Spanish")
        runs = len(lkm_history.list_runs("u", "Spanish"))
        km.recompute("u", "Spanish")
        assert len(lkm_history.list_runs("u", "Spanish")) == runs

    def test_retracting_all_evidence_removes_the_skill(self, temp_storage):
        km = KnowledgeModel()
        events = _events("u", 2)
        km.update_from_events("u", "Spanish", _dump(events))
        for e in events:
            store.supersede_event(e.event_id, reason="test")
        estimates = km.recompute("u", "Spanish")
        assert "vocabulary" not in estimates
        assert "vocabulary" not in skill_state.get_skills("u", "Spanish")
        with get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 2

    def test_unknown_event_cannot_be_superseded(self, temp_storage):
        with pytest.raises(KeyError):
            store.supersede_event("nope")
