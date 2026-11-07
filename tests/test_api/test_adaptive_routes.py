"""Adaptive-learning API (ADR-0033): recommendations, path, predictions, audit, reviews."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.evidence import store
from src.evidence.events import EventType, LearningEvent
from src.evidence.provenance import Provenance


def _seed_grammar(user_id: str) -> None:
    now = datetime.now(UTC)
    events = []
    for s in range(3):
        for i in range(4):
            events.append(
                LearningEvent.create(
                    EventType.GRAMMAR_ERROR if i < 3 else EventType.GRAMMAR_SUCCESS,
                    user_id,
                    "Spanish",
                    provenance=Provenance(source="test", session_id=f"s{s}"),
                    skill="grammar",
                    subskill="ser_vs_estar",
                    objective_id="grammar.ser_vs_estar",
                    item_id=f"ser_vs_estar#{s}{i}",
                    assessment="correct" if i == 3 else "incorrect",
                    confidence=0.9,
                    difficulty=0.25,
                    created_at=(now - timedelta(days=6 - 2 * s, minutes=i)).isoformat(),
                )
            )
    store.record_events(events)


class TestAdaptiveRoutes:
    def test_recommendations_are_explained_and_recorded(self, auth_client):
        client, headers, user_id = auth_client
        _seed_grammar(user_id)
        resp = client.get("/api/v1/learner/recommendations?language=Spanish", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["engine"] == "adaptive-nba-v1" and body["decision_id"]
        rec = next(r for r in body["recommendations"] if r["target"] == "ser_vs_estar")
        assert rec["intent"] == "remediation"
        assert rec["rationale"] and rec["evidence"]["event_ids"]
        assert rec["difficulty"]["linguistic_level"] == "A2"
        assert rec["predicted_success"]["kind"] == "prediction"

        trail = client.get("/api/v1/learner/decisions?language=Spanish", headers=headers).json()
        assert trail["decisions"][0]["id"] == body["decision_id"]
        assert trail["decisions"][0]["input_digest"] == body["input_digest"]

    def test_preview_is_not_recorded(self, auth_client):
        client, headers, _ = auth_client
        resp = client.get("/api/v1/learner/recommendations?record=false", headers=headers)
        assert resp.json()["decision_id"] is None
        trail = client.get("/api/v1/learner/decisions", headers=headers).json()
        assert trail["decisions"] == []

    def test_path_explains_changes_between_calls(self, auth_client):
        client, headers, user_id = auth_client
        first = client.get("/api/v1/learner/path?language=Spanish", headers=headers).json()
        assert first["changes"] == [] and first["steps"]
        _seed_grammar(user_id)
        second = client.get("/api/v1/learner/path?language=Spanish", headers=headers).json()
        change = next(c for c in second["changes"] if c["objective_id"] == "grammar.ser_vs_estar")
        assert change["from"] == "not_started" and change["to"] == "weak"

    def test_predictions_are_labelled_and_validated(self, auth_client):
        client, headers, user_id = auth_client
        _seed_grammar(user_id)
        resp = client.get(
            "/api/v1/learner/predictions?skill=grammar&subskill=ser_vs_estar&difficulty=0.25",
            headers=headers,
        )
        body = resp.json()
        assert body["kind"] == "prediction" and body["success"]["basis"] == "subskill"
        assert 0.0 < body["success"]["p_success"] < 0.5
        assert len(body["performance_curve"]) == 6
        assert body["forgetting"]["demonstrated"] is True
        bad = client.get("/api/v1/learner/predictions?skill=grammar&difficulty=2", headers=headers)
        assert bad.status_code == 422

    def test_review_submit_runs_fsrs_and_records_evidence(self, auth_client):
        client, headers, user_id = auth_client
        from src.memory import vocabulary_db

        vocabulary_db.upsert_word(
            user_id, "Spanish", "mesa", next_review="2020-01-01T00:00:00+00:00"
        )
        resp = client.post(
            "/api/v1/review/submit?language=Spanish",
            json={"word": "mesa", "correct": True, "mode": "production"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["next_review"] > "2020-01-01"
        row = vocabulary_db.get_all_for_user(user_id, "Spanish")[0]
        assert row["next_review"] > "2020-01-01" and row["production"] > 0.0
        (event,) = store.get_events(user_id, "Spanish", event_type="REVIEW_RESULT")
        assert event["subskill"] == "production"
        mismatch = client.post(
            "/api/v1/review/submit",
            json={"word": "mesa", "correct": True, "rating": 1},
            headers=headers,
        )
        assert mismatch.status_code == 422

    def test_privacy_export_and_delete_cover_decisions(self, auth_client):
        client, headers, user_id = auth_client
        client.get("/api/v1/learner/recommendations", headers=headers)
        from src.adaptive import audit
        from src.memory.privacy import delete_user_data, export_user_data

        assert len(export_user_data(user_id)["adaptive_decisions"]) == 1
        assert delete_user_data(user_id)["adaptive_decisions"] == 1
        assert audit.all_for_user(user_id) == []

    def test_schema_reaches_version_8(self, temp_storage):
        from src.memory import schema

        assert schema.run_migrations() == schema.SCHEMA_VERSION == 8
