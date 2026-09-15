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

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from src import evidence
from src.agents.assessment import assessment_node
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
    vocab_events = [e for e in events if e.event_type == EventType.VOCAB_PRODUCED]

    # --- Derive vocabulary belief -> personal lexicon, scheduled via FSRS. ---
    new_vocab: list[dict[str, Any]] = [
        {
            "word": e.item_id,
            "translation": e.payload.get("translation", ""),
            "pos": e.payload.get("pos", ""),
            "context_sentence": e.payload.get("context_sentence", ""),
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
    try:
        analytics.log_session(
            user_id,
            language,
            session_type=state.get("mode", "conversation"),
            duration_minutes=duration_minutes,
            words_practiced=len(vocab_events),
            new_words_learned=vocab_written,
            grammar_errors=errors_written,
            cefr_estimate=state.get("cefr_level"),
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


def build_session_report(state: LearnerState) -> str:
    """Compile the end-of-session report from all agents' outputs.

    Includes grammar corrections, new vocabulary, cultural notes, the CEFR
    estimate, and cross-language transfer suggestions — one section per agent.
    """
    grammar_errors = state.get("grammar_errors", [])
    new_vocab = state.get("new_vocabulary", [])
    cultural_notes = state.get("cultural_notes", [])
    transfers = state.get("transfer_suggestions", [])

    lines = ["\n" + "━" * 50, "📊 Session Report", "━" * 50]

    # Grammar
    if grammar_errors:
        lines.append(f"🔤 Grammar — {len(grammar_errors)} correction(s):")
        for e in grammar_errors[:10]:
            lines.append(f"   • {e.get('original', '')} → {e.get('correction', '')}")
    else:
        lines.append("🔤 Grammar — no errors detected")

    # Vocabulary
    if new_vocab:
        words = ", ".join(v.get("word", "") for v in new_vocab[:15])
        lines.append(f"📚 New vocabulary ({len(new_vocab)}): {words}")
    else:
        lines.append("📚 New vocabulary — none this session")

    # Cultural
    if cultural_notes:
        lines.append(f"🌍 Cultural notes ({len(cultural_notes)}):")
        for note in cultural_notes[:5]:
            lines.append(f"   • {note}")

    # CEFR
    lines.append(f"📈 Level estimate: {state.get('cefr_level', 'unknown')}")

    # Scenario outcome (Phase 13): did the learner meet the scenario's goals?
    scenario_ctx = state.get("current_scenario") or {}
    scenario_id = scenario_ctx.get("scenario_id")
    if scenario_id:
        outcome = _evaluate_scenario_outcome(state, scenario_id)
        if outcome is not None:
            status = "✅ passed" if outcome["passed"] else "◻ not yet"
            lines.append(f"🎯 Scenario '{scenario_id}': {status}")
            lines.append(
                f"   objectives {'✓' if outcome['objectives_completed'] else '✗'}"
                f" | target vocab {int(outcome['vocab_coverage'] * 100)}%"
                f" | grammar {'ok' if outcome['grammar_ok'] else 'high error rate'}"
            )
            for reason in outcome.get("failure_reasons", []):
                lines.append(f"   ⚠ failure: {reason}")

    # Cross-language transfer
    if transfers:
        lines.append("🔗 Cross-language transfer:")
        for t in transfers[:10]:
            cognates = t.get("cognates", {})
            if cognates:
                pairs = ", ".join(f"{lang}: {w}" for lang, w in cognates.items())
                lines.append(f"   • {t['word']} → {pairs}")
            for ff in t.get("false_friends", []):
                lines.append(
                    f"   ⚠ false friend — {ff.get('language')}: "
                    f"{ff.get('word')} ({ff.get('warning', '')})"
                )

    lines.append("━" * 50 + "\n")
    return "\n".join(lines)


async def finalize_session(state: LearnerState, *, duration_minutes: float = 0.0) -> dict[str, Any]:
    """Run end-of-session agents, persist outputs, and build the report.

    Order:
    1. Assessment agent — recompute CEFR and persist to profile.
    2. Transfer agent — cognate/false-friend suggestions for new vocab.
    3. Persist vocabulary, grammar errors, turns, and session metrics.
    4. Compile the enriched report.

    Returns ``{"report": str, "persisted": {...counts...}}``.
    """
    # 1. Assessment (updates cefr_level on state + profile).
    assessment_update = await assessment_node(state)
    state["cefr_level"] = assessment_update["cefr_level"]

    # 2. Transfer (populates transfer_suggestions).
    transfer_update = await transfer_node(state)
    state["transfer_suggestions"] = transfer_update["transfer_suggestions"]

    # 3. Persist everything.
    counts = persist_session(state, duration_minutes=duration_minutes)

    # 4. Report.
    report = build_session_report(state)
    state["agent_response"] = report
    state["should_end_session"] = True

    return {"report": report, "persisted": counts}
