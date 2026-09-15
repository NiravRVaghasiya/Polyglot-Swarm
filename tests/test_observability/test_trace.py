"""Phase 17 tests: the trace assembler (evidence + model_runs -> Trace)."""

from __future__ import annotations

from src.evidence.events import EventType, LearningEvent
from src.evidence.provenance import Provenance
from src.evidence.store import record_events
from src.llm.telemetry import ModelRun
from src.memory.model_runs import record_run
from src.observability.links import interactions_for_session, record_link
from src.observability.trace import Span, Trace, assemble_trace, format_trace


def _evidence(
    user_id="u1", session_id="s1", interaction_id=None, event_type=EventType.TURN_COMPLETED
):
    return LearningEvent.create(
        event_type,
        user_id,
        "Spanish",
        provenance=Provenance(source="test", session_id=session_id, interaction_id=interaction_id),
        observed="hola",
    )


class TestAssembleTraceEmpty:
    def test_no_records_yields_empty_trace(self, temp_storage):
        trace = assemble_trace("u1", "s-none")
        assert trace.session_id == "s-none"
        assert trace.user_id == "u1"
        assert trace.spans == []
        assert trace.interactions == []


class TestAssembleTraceEvidenceOnly:
    def test_evidence_without_interaction_id_has_no_model_runs(self, temp_storage):
        record_events([_evidence()])
        trace = assemble_trace("u1", "s1")
        assert len(trace.spans) == 1
        assert trace.spans[0].kind == "evidence"
        assert trace.interactions == []

    def test_evidence_scoped_to_session(self, temp_storage):
        record_events([_evidence(session_id="s1"), _evidence(session_id="s2")])
        trace = assemble_trace("u1", "s1")
        assert len(trace.spans) == 1

    def test_evidence_scoped_to_user(self, temp_storage):
        record_events([_evidence(user_id="u1"), _evidence(user_id="u2")])
        trace_u1 = assemble_trace("u1", "s1")
        trace_u2 = assemble_trace("u2", "s1")
        assert len(trace_u1.spans) == 1
        assert len(trace_u2.spans) == 1


class TestAssembleTraceJoinsModelRuns:
    def test_model_run_joined_via_evidence_interaction_id(self, temp_storage):
        record_events([_evidence(interaction_id="iid-1")])
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-1"))
        # A run under a different interaction must not leak in.
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-2"))

        trace = assemble_trace("u1", "s1")
        kinds = [s.kind for s in trace.spans]
        assert kinds.count("evidence") == 1
        assert kinds.count("model_run") == 1
        assert trace.interactions == ["iid-1"]

    def test_model_run_joined_via_link_table_without_evidence(self, temp_storage):
        # No evidence at all — only the session<->interaction link (this is the
        # common case: a turn that produced no grammar/vocab findings).
        record_link("s1", "iid-1", user_id="u1")
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-1"))

        trace = assemble_trace("u1", "s1")
        assert len(trace.spans) == 1
        assert trace.spans[0].kind == "model_run"
        assert trace.interactions == ["iid-1"]

    def test_link_table_scoped_to_user(self, temp_storage):
        # Another user's link to the same session id must not leak this
        # user's trace into someone else's model-run telemetry.
        record_link("s1", "iid-other-user", user_id="u2")
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-other-user"))

        trace = assemble_trace("u1", "s1")
        assert trace.spans == []

    def test_multiple_interactions_ordered_by_timestamp(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_link("s1", "iid-2", user_id="u1")
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-1"))
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-2"))

        trace = assemble_trace("u1", "s1")
        assert len(trace.spans) == 2
        timestamps = [s.timestamp for s in trace.spans]
        assert timestamps == sorted(timestamps)


class TestInteractionsForSession:
    def test_idempotent_link(self, temp_storage):
        record_link("s1", "iid-1", user_id="u1")
        record_link("s1", "iid-1", user_id="u1")  # duplicate, ignored
        assert interactions_for_session("s1") == ["iid-1"]

    def test_ignores_blank_ids(self, temp_storage):
        record_link("", "iid-1", user_id="u1")
        record_link("s1", "", user_id="u1")
        assert interactions_for_session("s1") == []


class TestTraceHelpers:
    def test_for_interaction_filters_spans(self):
        trace = Trace(
            session_id="s1",
            user_id="u1",
            spans=[
                Span(kind="evidence", timestamp="t1", interaction_id="a", summary="x"),
                Span(kind="model_run", timestamp="t2", interaction_id="b", summary="y"),
            ],
        )
        assert len(trace.for_interaction("a")) == 1
        assert trace.interactions == ["a", "b"]

    def test_as_dict_shape(self):
        trace = Trace(session_id="s1", user_id="u1", spans=[])
        d = trace.as_dict()
        assert d == {"session_id": "s1", "user_id": "u1", "interactions": [], "spans": []}


class TestFormatTrace:
    def test_format_empty_trace(self):
        text = format_trace(Trace(session_id="s1", user_id="u1", spans=[]))
        assert "s1" in text
        assert "no recorded spans" in text

    def test_format_includes_interaction_and_spans(self, temp_storage):
        record_events([_evidence(interaction_id="iid-1")])
        record_run(ModelRun(provider="fake", tier="primary", interaction_id="iid-1"))
        trace = assemble_trace("u1", "s1")

        text = format_trace(trace)
        assert "iid-1" in text
        assert "evidence" in text
        assert "model_run" in text
        # ASCII-only: no unicode arrows/box glyphs that would crash cp1252
        # consoles (Windows CLI).
        text.encode("ascii")

    def test_format_uncorrelated_section(self, temp_storage):
        record_events([_evidence(interaction_id=None)])
        trace = assemble_trace("u1", "s1")
        text = format_trace(trace)
        assert "uncorrelated" in text
