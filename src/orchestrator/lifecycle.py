"""Session lifecycle — bridges the LangGraph state and the persistence layer.

Two responsibilities:

- :func:`build_initial_state` seeds a fresh :class:`LearnerState` from the
  learner's persistent profile (CEFR, weaknesses, interests) and any vocabulary
  currently due for review, so every session starts already personalized.

- :func:`persist_session` writes the outputs accumulated during a session back
  to durable storage: new vocabulary, grammar error patterns, conversation
  turns, and the session metrics used by analytics.

Keeping this logic out of the pure graph nodes lets the same wiring be reused
by the CLI, the Gradio app, and the API.

Note on scheduling: full FSRS scheduling lives in the later SRS task. Here new
vocabulary is scheduled with a simple next-day default so cross-session review
surfacing works end to end today.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src import evidence
from src.agents.assessment import persist_evidence_profile, update_working_level
from src.agents.srs import schedule_new_items
from src.agents.transfer import transfer_node
from src.evidence.events import EventType
from src.learner import get_knowledge_model
from src.memory import analytics, session_history, sessions, user_profile, vocabulary_db
from src.orchestrator.state import LearnerState

logger = logging.getLogger("polyglot.lifecycle")


def _default_scenario(language: str) -> dict[str, Any]:
    return {
        "persona": {
            "name": "Ana",
            "role": "friendly local",
            "personality": "warm, patient, encouraging",
        },
        "location": "city center",
        "objectives": ["have a natural conversation"],
        "context": "casual meeting",
    }


# Scenario language codes -> the free-form language names the agents use.
_LANG_CODE_TO_NAME = {"es": "Spanish", "pl": "Polish", "it": "Italian"}


def build_initial_state(
    user_id: str,
    language: str | None = None,
    *,
    session_id: str | None = None,
    scenario: dict[str, Any] | None = None,
    scenario_id: str | None = None,
    mode: str = "conversation",
) -> LearnerState:
    """Build a personalized initial state for a session.

    Loads the user's profile (creating a default if none exists), applies their
    CEFR/weaknesses/interests, and loads any due vocabulary into
    ``pending_reviews`` so the router can offer a review at session start.

    If ``scenario_id`` is given, the matching scenario is loaded and its context
    (persona, objectives, difficulty for the learner's level) is injected; the
    session language defaults to the scenario's language.
    """
    profile = user_profile.load_profile(user_id)

    loaded_scenario = None
    if scenario_id is not None:
        from src.scenarios.loader import get_scenario

        loaded_scenario = get_scenario(scenario_id)
        if language is None:
            language = _LANG_CODE_TO_NAME.get(loaded_scenario.language, loaded_scenario.language)

    lang = language or (profile.target_languages[0] if profile.target_languages else "Spanish")

    if loaded_scenario is not None:
        from src.scenarios.engine import build_scenario_context

        scenario = build_scenario_context(loaded_scenario, profile.cefr_for(lang))

    due = vocabulary_db.get_due(user_id, lang, limit=20)

    resolved_session_id = session_id or str(uuid.uuid4())

    # Record the session lifecycle so it is resumable/auditable (Phase 2).
    sessions.start_session(
        resolved_session_id,
        user_id,
        lang,
        mode=mode,
        scenario_id=scenario_id,
    )

    return LearnerState(
        session_id=resolved_session_id,
        user_id=user_id,
        language=lang,
        mode=mode,
        messages=[],
        current_scenario=scenario or _default_scenario(lang),
        current_persona=None,
        grammar_errors=[],
        new_vocabulary=[],
        cultural_notes=[],
        evaluation=None,
        transfer_suggestions=[],
        cefr_level=profile.cefr_for(lang),
        vocabulary_known_count=vocabulary_db.count_for_user(user_id, lang),
        grammar_weaknesses=analytics.top_weaknesses(user_id, lang),
        user_interests=profile.interests,
        turn_count=0,
        should_end_session=False,
        pending_reviews=due,
        last_user_input="",
        agent_response="",
    )


def persist_session(state: LearnerState, *, duration_minutes: float = 0.0) -> dict[str, int]:
    """Persist a completed session's outputs to durable storage.

    Writes new vocabulary, grammar error patterns, conversation turns, and a
    session-metrics row. Returns counts of what was written for reporting/tests.
    """
    user_id = state["user_id"]
    language = state["language"]

    # --- Evidence pipeline: emit + persist structured events FIRST. ---
    # This separates "what happened" (events) from "what we believe" (the
    # vocabulary lexicon and grammar error taxonomy derived below). The belief
    # layer is fed from the deduplicated, normalized events rather than directly
    # from raw LLM output.
    events = evidence.process_session(dict(state))
    grammar_events = [e for e in events if e.event_type == EventType.GRAMMAR_ERROR]
    # Both learner-produced words and words met in the tutor's reply join the
    # lexicon (and the FSRS deck); only produced ones count toward the
    # production dimension below (ADR-0031: exposure is not mastery).
    vocab_events = [
        e for e in events if e.event_type in (EventType.VOCAB_PRODUCED, EventType.VOCAB_OBSERVED)
    ]

    # --- Derive vocabulary belief -> personal lexicon, scheduled via FSRS. ---
    new_vocab: list[dict[str, Any]] = [
        {
            "word": e.item_id,
            "translation": e.payload.get("translation", ""),
            "pos": e.payload.get("pos", ""),
            "context_sentence": e.payload.get("context_sentence", ""),
            "produced": e.event_type == EventType.VOCAB_PRODUCED,
        }
        for e in vocab_events
        if e.item_id
    ]
    scheduled = schedule_new_items(new_vocab)
    vocab_written = 0
    now_iso = datetime.now(UTC).isoformat()
    for item, card in zip(new_vocab, scheduled, strict=True):
        word = item["word"]
        vocabulary_db.upsert_word(
            user_id,
            language,
            word,
            translation=item.get("translation", ""),
            pos=item.get("pos", ""),
            context=item.get("context_sentence") or None,
            card_state=card["card_state"],
            next_review=card["next_review"],
        )
        # Phase 5: a produced word is evidence toward the production dimension,
        # and stamp first_seen. The word row now exists (upserted above).
        vocabulary_db.set_metadata(user_id, language, word, first_seen=now_iso)
        if item["produced"]:
            vocabulary_db.record_dimension(
                user_id, language, word, "production", success=True, at=now_iso
            )
        vocab_written += 1

    # --- Derive grammar belief -> persistent error taxonomy (from events). ---
    # Phase 23: analytics is a durable secondary store, not the record of truth
    # for "did this session happen" (that's src.memory.sessions, updated below).
    # A failure writing one error-pattern row must not abort the rest of
    # finalization — the evidence pipeline already persisted the underlying
    # events above, so this is best-effort enrichment on top of that.
    errors_written = 0
    for e in grammar_events:
        try:
            analytics.record_error(user_id, language, e.item_id or "unknown")
            errors_written += 1
        except Exception as exc:  # noqa: BLE001 - analytics must never block finalization
            logger.error(
                "analytics.record_error failed for user=%s error_type=%s: %s",
                user_id,
                e.item_id,
                exc,
            )

    # --- Conversation turns -> session history (durable turn log). ---
    turns_written = session_history.record_turns(
        state["session_id"], user_id, language, state.get("messages", [])
    )

    # --- Session metrics -> analytics (best-effort; see note above). ---
    # Only a *recorded* working level is logged; the instructional default a
    # brand-new learner starts on is not an estimate (ADR-0031).
    try:
        working_level = (
            state.get("cefr_level")
            if user_profile.load_profile(user_id).has_working_level(language)
            else None
        )
        analytics.log_session(
            user_id,
            language,
            session_type=state.get("mode", "conversation"),
            duration_minutes=duration_minutes,
            words_practiced=len(vocab_events),
            new_words_learned=vocab_written,
            grammar_errors=errors_written,
            cefr_estimate=working_level,
        )
    except Exception as exc:  # noqa: BLE001 - analytics must never block finalization
        logger.error("analytics.log_session failed for session=%s: %s", state["session_id"], exc)

    # --- Learner model: update skill beliefs from THIS session's events. ---
    # The knowledge model consumes the evidence (already persisted above),
    # producing posterior mastery + uncertainty per skill, then snapshots the
    # model for longitudinal analysis (Phase 6).
    model = get_knowledge_model()
    model.update_from_events(user_id, language, [e.model_dump() for e in events])
    model.snapshot(user_id, language, reason="session_end")

    # --- Session lifecycle -> mark completed (resumable registry, Phase 2). ---
    sessions.end_session(state["session_id"], status="completed")

    return {
        "vocabulary": vocab_written,
        "grammar_errors": errors_written,
        "turns": turns_written,
        "events": len(events),
    }


def _evaluate_scenario_outcome(state: LearnerState, scenario_id: str) -> dict[str, Any] | None:
    """Evaluate the scenario's success/failure for the report (best-effort).

    Reconstructs the :class:`Scenario` by id and runs ``evaluate_success`` over
    the conversation. Returns ``None`` if the scenario can't be loaded (e.g. a
    default/ad-hoc scenario), so the report simply omits the section.
    """
    from src.scenarios.engine import evaluate_success
    from src.scenarios.loader import ScenarioError, get_scenario

    try:
        scenario = get_scenario(scenario_id)
    except ScenarioError:
        return None

    messages = state.get("messages", [])
    user_turns = [m for m in messages if m.get("role") == "user"]
    error_rate = len(state.get("grammar_errors", [])) / max(len(user_turns), 1)
    return evaluate_success(scenario, messages, grammar_error_rate=error_rate)


def _level_summary(state: LearnerState) -> dict[str, Any]:
    """The evidence-backed CEFR estimate and its status, kept apart from the
    tutor's working level (ADR-0031). ``estimate`` is ``None`` until the
    evidence supports a level; ``status`` is ``None`` if the model is unavailable."""
    working = state.get("cefr_level", "unknown")
    try:
        from src.assessment.cefr_profile import build_cefr_profile

        profile = build_cefr_profile(state["user_id"], state["language"])
    except Exception:  # noqa: BLE001 - the report must render even if the model can't
        return {"estimate": None, "status": None, "working_level": working}
    return {
        "estimate": profile.overall,
        "status": profile.overall_status.replace("_", " "),
        "working_level": working,
    }


def build_session_summary(state: LearnerState) -> dict[str, Any]:
    """The end-of-session report as data, one section per agent.

    Grammar corrections, new vocabulary, cultural notes, the level estimate
    next to the tutor's working level, the scenario outcome, and
    cross-language transfer suggestions. The API serves it as ``summary``;
    :func:`build_session_report` renders the same data as text.
    """
    grammar_errors = state.get("grammar_errors", [])
    new_vocab = state.get("new_vocabulary", [])
    scenario: dict[str, Any] | None = None
    scenario_id = (state.get("current_scenario") or {}).get("scenario_id")
    if scenario_id:
        outcome = _evaluate_scenario_outcome(state, scenario_id)
        if outcome is not None:
            scenario = {
                "id": scenario_id,
                "passed": bool(outcome["passed"]),
                "objectives_completed": bool(outcome["objectives_completed"]),
                "vocab_coverage": float(outcome["vocab_coverage"]),
                "grammar_ok": bool(outcome["grammar_ok"]),
                "failure_reasons": [str(r) for r in outcome.get("failure_reasons", [])],
            }
    return {
        "correction_count": len(grammar_errors),
        "corrections": [
            {
                "original": str(e.get("original", "")),
                "correction": str(e.get("correction", "")),
                "explanation": str(e.get("explanation") or ""),
            }
            for e in grammar_errors[:10]
        ],
        "new_word_count": len(new_vocab),
        "new_words": [str(v.get("word", "")) for v in new_vocab[:15]],
        "cultural_notes": [str(n) for n in state.get("cultural_notes", [])[:5]],
        "level": _level_summary(state),
        "scenario": scenario,
        "transfers": [
            {
                "word": str(t.get("word", "")),
                "cognates": {str(k): str(v) for k, v in (t.get("cognates") or {}).items()},
                "false_friends": [
                    {
                        "language": str(ff.get("language", "")),
                        "word": str(ff.get("word", "")),
                        "warning": str(ff.get("warning", "")),
                    }
                    for ff in t.get("false_friends", [])
                ],
            }
            for t in state.get("transfer_suggestions", [])[:10]
        ],
    }


def _level_line(level: dict[str, Any]) -> str:
    working = level["working_level"]
    if level["status"] is None:
        return f"📈 Level estimate: unavailable · tutor working level {working}"
    if level["estimate"] is None:
        return f"📈 Level estimate: not yet ({level['status']}) · tutor working level {working}"
    return (
        f"📈 Level estimate: {level['estimate']} ({level['status']})"
        f" · tutor working level {working}"
    )


def render_session_report(summary: dict[str, Any]) -> str:
    """The text form of :func:`build_session_summary` (CLI, Gradio, API ``report``)."""
    lines = ["\n" + "━" * 50, "📊 Session Report", "━" * 50]

    if summary["corrections"]:
        lines.append(f"🔤 Grammar — {summary['correction_count']} correction(s):")
        for e in summary["corrections"]:
            lines.append(f"   • {e['original']} → {e['correction']}")
    else:
        lines.append("🔤 Grammar — no errors detected")

    if summary["new_words"]:
        words = ", ".join(summary["new_words"])
        lines.append(f"📚 New vocabulary ({summary['new_word_count']}): {words}")
    else:
        lines.append("📚 New vocabulary — none this session")

    if summary["cultural_notes"]:
        lines.append(f"🌍 Cultural notes ({len(summary['cultural_notes'])}):")
        for note in summary["cultural_notes"]:
            lines.append(f"   • {note}")

    lines.append(_level_line(summary["level"]))

    scenario = summary["scenario"]
    if scenario is not None:
        status = "✅ passed" if scenario["passed"] else "◻ not yet"
        lines.append(f"🎯 Scenario '{scenario['id']}': {status}")
        lines.append(
            f"   objectives {'✓' if scenario['objectives_completed'] else '✗'}"
            f" | target vocab {int(scenario['vocab_coverage'] * 100)}%"
            f" | grammar {'ok' if scenario['grammar_ok'] else 'high error rate'}"
        )
        for reason in scenario["failure_reasons"]:
            lines.append(f"   ⚠ failure: {reason}")

    if summary["transfers"]:
        lines.append("🔗 Cross-language transfer:")
        for t in summary["transfers"]:
            if t["cognates"]:
                pairs = ", ".join(f"{lang}: {w}" for lang, w in t["cognates"].items())
                lines.append(f"   • {t['word']} → {pairs}")
            for ff in t["false_friends"]:
                lines.append(
                    f"   ⚠ false friend — {ff['language']}: {ff['word']} ({ff['warning']})"
                )

    lines.append("━" * 50 + "\n")
    return "\n".join(lines)


def build_session_report(state: LearnerState) -> str:
    """Compile the end-of-session report text from all agents' outputs."""
    return render_session_report(build_session_summary(state))


async def finalize_session(state: LearnerState, *, duration_minutes: float = 0.0) -> dict[str, Any]:
    """Run end-of-session agents, persist outputs, and build the report.

    Order:
    1. Working level — re-estimate the tutor's pitch from this session.
    2. Transfer agent — cognate/false-friend suggestions for new vocab.
    3. Persist evidence, vocabulary, grammar errors, turns, session metrics and
       the learner model; then persist the evidence-backed CEFR profile.
    4. Compile the enriched report.

    Returns ``{"report": str, "summary": {...}, "persisted": {...counts...}}``. The SQLite work
    (steps 1 and 3) runs in worker threads, off the event loop.
    """
    # 1. Working level (updates cefr_level on state + profile when the session
    #    gave a signal; never records a default).
    state["cefr_level"] = await asyncio.to_thread(update_working_level, state)

    # 2. Transfer (populates transfer_suggestions).
    transfer_update = await transfer_node(state)
    state["transfer_suggestions"] = transfer_update["transfer_suggestions"]

    # 3. Persist everything (evidence first, then the learner model).
    counts = await asyncio.to_thread(persist_session, state, duration_minutes=duration_minutes)

    # 3b. The evidence-backed CEFR profile, built *after* this session's
    #     evidence reached the learner model (it used to be built before, so
    #     the persisted profile lagged one session behind).
    await asyncio.to_thread(persist_evidence_profile, state["user_id"], state["language"])

    # 4. Report, as data and as text.
    summary = build_session_summary(state)
    report = render_session_report(summary)
    state["agent_response"] = report
    state["should_end_session"] = True

    return {"report": report, "summary": summary, "persisted": counts}
