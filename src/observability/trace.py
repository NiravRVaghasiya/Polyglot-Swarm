"""Trace assembler — reconstruct a turn from the records it left behind.

Two durable signals already describe what the tutor did during a session:

- **model runs** (:mod:`src.memory.model_runs`) — every LLM call, with
  provider/model/latency/tokens/cost and, since Phase 17, an ``interaction_id``.
- **evidence events** (:mod:`src.evidence.store`) — the structured, append-only
  record of what the learner model observed (grammar errors, assessments,
  curriculum decisions), each tagged with ``session_id`` and ``interaction_id``.

This module stitches those into a :class:`Trace`: a session's spans, ordered in
time and grouped by interaction, so a bad tutor response can be reconstructed
end-to-end. It introduces no new storage — it only reads what Phases 2 and 3
already persist, joined on the correlation key Phase 17 adds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    """One recorded step within a turn (a model call or an evidence event)."""

    kind: str  # "model_run" | "evidence"
    timestamp: str
    interaction_id: str | None
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "timestamp": self.timestamp,
            "interaction_id": self.interaction_id,
            "summary": self.summary,
            "detail": self.detail,
        }


@dataclass
class Trace:
    """The ordered spans for a session, plus per-interaction grouping."""

    session_id: str
    user_id: str
    spans: list[Span] = field(default_factory=list)

    @property
    def interactions(self) -> list[str]:
        """Distinct interaction ids seen in this trace, in first-seen order."""
        seen: list[str] = []
        for span in self.spans:
            iid = span.interaction_id
            if iid is not None and iid not in seen:
                seen.append(iid)
        return seen

    def for_interaction(self, interaction_id: str) -> list[Span]:
        """The spans belonging to a single interaction."""
        return [s for s in self.spans if s.interaction_id == interaction_id]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "interactions": self.interactions,
            "spans": [s.as_dict() for s in self.spans],
        }


def _model_run_to_span(run: dict[str, Any]) -> Span:
    provider = run.get("provider")
    model = run.get("model")
    tier = run.get("tier")
    ok = bool(run.get("success", 1))
    status = "ok" if ok else "FAILED"
    summary = f"llm {provider}/{model or '?'} tier={tier} {status}"
    return Span(
        kind="model_run",
        timestamp=str(run.get("created_at") or run.get("timestamp") or ""),
        interaction_id=run.get("interaction_id"),
        summary=summary,
        detail={
            "provider": provider,
            "tier": tier,
            "model": model,
            "operation": run.get("operation"),
            "latency_ms": run.get("latency_ms"),
            "input_tokens": run.get("input_tokens"),
            "output_tokens": run.get("output_tokens"),
            "cost_usd": run.get("cost_usd"),
            "success": ok,
            "error": run.get("error"),
        },
    )


def _evidence_to_span(event: dict[str, Any]) -> Span:
    etype = event.get("event_type")
    skill = event.get("skill")
    assessment = event.get("assessment")
    bits = [str(etype)]
    if skill:
        bits.append(f"skill={skill}")
    if assessment:
        bits.append(f"assessment={assessment}")
    return Span(
        kind="evidence",
        timestamp=str(event.get("created_at") or ""),
        interaction_id=event.get("interaction_id"),
        summary=" ".join(bits),
        detail={
            "event_type": etype,
            "skill": skill,
            "item_id": event.get("item_id"),
            "observed": event.get("observed"),
            "expected": event.get("expected"),
            "assessment": assessment,
            "confidence": event.get("confidence"),
            "source": event.get("source"),
        },
    )


def assemble_trace(
    user_id: str,
    session_id: str,
    *,
    language: str | None = None,
    limit: int = 500,
) -> Trace:
    """Stitch model runs and evidence events for a session into a :class:`Trace`.

    The two record streams are read independently (evidence is filtered in SQL
    by ``session_id``; model runs are filtered in memory by the interaction ids
    seen in this session, because the runs table has no session column) and
    merged into a single timeline ordered by timestamp.

    Args:
        user_id: Owner of the session (evidence is per-user).
        session_id: The session to reconstruct.
        language: Optional language filter for evidence.
        limit: Max records to pull from each source.

    Returns:
        A :class:`Trace` whose spans are ordered oldest-first.
    """
    from src.evidence.store import get_events
    from src.memory.model_runs import get_runs
    from src.observability.links import interactions_for_session

    events = get_events(user_id, language, session_id=session_id, limit=limit)
    spans: list[Span] = [_evidence_to_span(e) for e in events]

    # The model_runs table records interaction_id but not session_id, so join
    # via the interaction ids known to belong to this session. Those come from
    # two sources, unioned: the explicit session<->interaction link recorded per
    # turn (authoritative, covers turns that produced no evidence), and any
    # interaction ids the session's evidence itself references.
    session_interactions: set[str] = set(interactions_for_session(session_id, user_id))
    session_interactions.update(e["interaction_id"] for e in events if e.get("interaction_id"))
    if session_interactions:
        for run in get_runs(limit=limit):
            if run.get("interaction_id") in session_interactions:
                spans.append(_model_run_to_span(run))

    spans.sort(key=lambda s: s.timestamp)
    return Trace(session_id=session_id, user_id=user_id, spans=spans)


def format_trace(trace: Trace) -> str:
    """Render a trace as an ASCII-safe, human-readable block.

    Kept ASCII-only (no unicode arrows/box glyphs) so it prints cleanly on
    Windows cp1252 consoles used by the CLI.
    """
    lines: list[str] = []
    lines.append(f"Trace session={trace.session_id} user={trace.user_id}")
    lines.append(f"  interactions: {len(trace.interactions)}  spans: {len(trace.spans)}")
    if not trace.spans:
        lines.append("  (no recorded spans)")
        return "\n".join(lines)

    for iid in trace.interactions or [None]:  # type: ignore[list-item]
        header = f"interaction {iid}" if iid is not None else "uncorrelated"
        lines.append(f"  [{header}]")
        span_group = (
            trace.for_interaction(iid)
            if iid is not None
            else [s for s in trace.spans if s.interaction_id is None]
        )
        for span in span_group:
            ts = span.timestamp or "?"
            lines.append(f"    - {ts} {span.kind}: {span.summary}")

    # Any spans with an interaction id not surfaced above (defensive) and
    # uncorrelated spans when interactions exist.
    if trace.interactions:
        orphans = [s for s in trace.spans if s.interaction_id is None]
        if orphans:
            lines.append("  [uncorrelated]")
            for span in orphans:
                ts = span.timestamp or "?"
                lines.append(f"    - {ts} {span.kind}: {span.summary}")

    return "\n".join(lines)
