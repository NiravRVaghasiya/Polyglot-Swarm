"""Phase 3 tests: evidence extraction, normalization, dedup, confidence,
persistence, and the persist_session integration."""

from __future__ import annotations

from src.evidence import build_events, confidence, deduplicator, extractor, normalizer, store
from src.evidence.events import EVENT_SKILL, EventType, LearningEvent
from src.evidence.provenance import Provenance


def _state(**overrides):
    state = {
        "user_id": "u1",
        "language": "Spanish",
        "session_id": "s1",
        "messages": [
            {"role": "user", "content": "Yo soy hambre"},
            {"role": "assistant", "content": "Se dice 'tengo hambre'."},
        ],
        "grammar_errors": [
            {
                "original": "Yo soy hambre",
                "correction": "Yo tengo hambre",
                "rule": "ser_vs_tener",
                "explanation": "use tener",
                "severity": "critical",
            }
        ],
        "new_vocabulary": [
            {"word": "hambre", "translation": "hunger", "pos": "noun"},
        ],
    }
    state.update(overrides)
    return state


class TestEventModel:
    def test_create_defaults_skill_from_type(self):
        e = LearningEvent.create(
            EventType.GRAMMAR_ERROR, "u1", "Spanish", provenance=Provenance("t")
        )
        assert e.skill == "grammar"
        assert e.event_id  # auto id
        assert e.source == "t"

    def test_event_skill_map_covers_all_types(self):
        for t in EventType:
            assert t in EVENT_SKILL

    def test_create_defaults_interaction_id_from_context(self):
        # Phase 17: when provenance doesn't carry an interaction_id, fall back
        # to whatever interaction is currently in scope.
        from src.observability.context import interaction_scope

        with interaction_scope(session_id="s1", interaction_id="iid-1"):
            e = LearningEvent.create(
                EventType.GRAMMAR_ERROR, "u1", "Spanish", provenance=Provenance("t")
            )
        assert e.interaction_id == "iid-1"

    def test_create_respects_explicit_provenance_interaction_id(self):
        # An explicit provenance value takes precedence over the contextvar.
        from src.observability.context import interaction_scope

        with interaction_scope(session_id="s1", interaction_id="ambient"):
            e = LearningEvent.create(
                EventType.GRAMMAR_ERROR,
                "u1",
                "Spanish",
                provenance=Provenance("t", interaction_id="explicit"),
            )
        assert e.interaction_id == "explicit"

    def test_create_interaction_id_none_outside_scope(self):
        e = LearningEvent.create(
            EventType.GRAMMAR_ERROR, "u1", "Spanish", provenance=Provenance("t")
        )
        assert e.interaction_id is None


class TestExtractor:
    def test_extracts_all_event_kinds(self):
        events = extractor.extract_from_state(_state())
        kinds = {e.event_type for e in events}
        assert EventType.TURN_COMPLETED in kinds
        assert EventType.GRAMMAR_ERROR in kinds
        assert EventType.VOCAB_PRODUCED in kinds

    def test_only_user_turns_become_turn_events(self):
        events = extractor.extract_turn_events(
            "u1", "Spanish", _state()["messages"], provenance=Provenance("t")
        )
        assert len(events) == 1
        assert events[0].observed == "Yo soy hambre"

    def test_grammar_event_carries_provenance_and_payload(self):
        events = extractor.extract_grammar_events(
            "u1", "Spanish", _state()["grammar_errors"], provenance=Provenance("grammar-v1")
        )
        assert events[0].source == "grammar-v1"
        assert events[0].expected == "Yo tengo hambre"
        assert events[0].payload["severity"] == "critical"

    def test_vocab_without_word_skipped(self):
        events = extractor.extract_vocabulary_events(
            "u1", "Spanish", [{"translation": "x"}], provenance=Provenance("t")
        )
        assert events == []


class TestNormalizer:
    def test_rule_normalization(self):
        assert normalizer.normalize_rule("Ser vs Estar") == "ser_vs_estar"
        assert normalizer.normalize_rule("  gender-agreement ") == "gender_agreement"
        assert normalizer.normalize_rule("") == "unknown"

    def test_word_normalization(self):
        assert normalizer.normalize_word("  Mesa ") == "mesa"

    def test_normalize_event_canonicalizes_item_id(self):
        e = LearningEvent.create(
            EventType.GRAMMAR_ERROR,
            "u1",
            "Spanish",
            provenance=Provenance("t"),
            item_id="Ser vs Estar",
        )
        assert normalizer.normalize_event(e).item_id == "ser_vs_estar"


class TestDeduplicator:
    def test_collapses_same_observation_keeps_highest_confidence(self):
        p = Provenance("t", session_id="s1")
        low = LearningEvent.create(
            EventType.VOCAB_PRODUCED, "u1", "Spanish", provenance=p, item_id="mesa", confidence=0.5
        )
        high = LearningEvent.create(
            EventType.VOCAB_PRODUCED, "u1", "Spanish", provenance=p, item_id="mesa", confidence=0.9
        )
        result = deduplicator.deduplicate([low, high])
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_distinct_items_kept(self):
        p = Provenance("t", session_id="s1")
        a = LearningEvent.create(
            EventType.VOCAB_PRODUCED, "u1", "Spanish", provenance=p, item_id="mesa"
        )
        b = LearningEvent.create(
            EventType.VOCAB_PRODUCED, "u1", "Spanish", provenance=p, item_id="silla"
        )
        assert len(deduplicator.deduplicate([a, b])) == 2


class TestConfidence:
    def test_provided_confidence_respected(self):
        assert confidence.score(EventType.GRAMMAR_ERROR, provided=0.3) == 0.3

    def test_severity_scales_grammar_confidence(self):
        minor = confidence.score(EventType.GRAMMAR_ERROR, severity="minor")
        critical = confidence.score(EventType.GRAMMAR_ERROR, severity="critical")
        assert critical > minor

    def test_produced_stronger_than_observed(self):
        assert confidence.base_confidence(EventType.VOCAB_PRODUCED) > confidence.base_confidence(
            EventType.VOCAB_OBSERVED
        )


class TestPipeline:
    def test_build_events_normalizes_and_dedups(self):
        state = _state(
            grammar_errors=[
                {"original": "a", "correction": "b", "rule": "Ser vs Tener", "severity": "high"},
                {"original": "a", "correction": "b", "rule": "ser_vs_tener", "severity": "high"},
            ]
        )
        events = build_events(state)
        grammar = [e for e in events if e.event_type == EventType.GRAMMAR_ERROR]
        assert len(grammar) == 1
        assert grammar[0].item_id == "ser_vs_tener"


class TestStore:
    def test_persist_and_query(self, temp_storage):
        from src.evidence import process_session

        events = process_session(_state())
        assert events
        stored = store.get_events("u1", "Spanish")
        assert len(stored) == len(events)

    def test_events_are_idempotent(self, temp_storage):
        events = build_events(_state())
        first = store.record_events(events)
        second = store.record_events(events)  # same event_ids -> no new rows
        assert first == len(events)
        assert second == 0

    def test_filter_by_type(self, temp_storage):
        from src.evidence import process_session

        process_session(_state())
        grammar = store.get_events("u1", "Spanish", event_type="GRAMMAR_ERROR")
        assert grammar
        assert all(e["event_type"] == "GRAMMAR_ERROR" for e in grammar)

    def test_count_events(self, temp_storage):
        from src.evidence import process_session

        process_session(_state())
        assert store.count_events("u1", "Spanish") == 3


class TestPersistSessionIntegration:
    def test_persist_session_emits_and_derives(self, temp_storage):
        from src.memory import analytics, vocabulary_db
        from src.orchestrator.lifecycle import build_initial_state, persist_session

        state = build_initial_state("learner", "Spanish", session_id="sess-x")
        state["messages"] = [{"role": "user", "content": "Yo soy hambre"}]
        state["grammar_errors"] = [
            {
                "original": "Yo soy hambre",
                "correction": "Yo tengo hambre",
                "rule": "Ser vs Tener",  # non-canonical -> normalized in events
                "severity": "critical",
            }
        ]
        state["new_vocabulary"] = [{"word": "hambre", "translation": "hunger", "pos": "noun"}]

        counts = persist_session(state)

        # Evidence was emitted and persisted.
        assert counts["events"] == 3
        assert store.count_events("learner", "Spanish") == 3

        # Belief layer derived FROM events: grammar error taxonomy uses the
        # normalized construction id, not the raw "Ser vs Tener".
        patterns = {p["error_type"] for p in analytics.get_error_patterns("learner", "Spanish")}
        assert "ser_vs_tener" in patterns

        # Vocabulary belief derived from the vocab event.
        words = {w["word"] for w in vocabulary_db.get_all_for_user("learner", "Spanish")}
        assert "hambre" in words
