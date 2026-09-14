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

import uuid
from typing import Any

from src.agents.assessment import assessment_node
from src.agents.srs import schedule_new_items
from src.agents.transfer import transfer_node
from src.memory import analytics, session_history, user_profile, vocabulary_db
from src.orchestrator.state import LearnerState


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
            language = _LANG_CODE_TO_NAME.get(
                loaded_scenario.language, loaded_scenario.language
            )

    lang = language or (
        profile.target_languages[0] if profile.target_languages else "Spanish"
    )

    if loaded_scenario is not None:
        from src.scenarios.engine import build_scenario_context

        scenario = build_scenario_context(loaded_scenario, profile.cefr_for(lang))

    due = vocabulary_db.get_due(user_id, lang, limit=20)

    return LearnerState(
        session_id=session_id or str(uuid.uuid4()),
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

    # --- New vocabulary -> personal lexicon, scheduled via FSRS. ---
    new_vocab: list[dict[str, Any]] = [
        dict(v) for v in state.get("new_vocabulary", []) if v.get("word")
    ]
    scheduled = schedule_new_items(new_vocab)
    vocab_written = 0
    for item, card in zip(new_vocab, scheduled, strict=True):
        vocabulary_db.upsert_word(
            user_id,
            language,
            item["word"],
            translation=item.get("translation", ""),
            pos=item.get("pos", ""),
            context=item.get("context_sentence") or None,
            card_state=card["card_state"],
            next_review=card["next_review"],
        )
        vocab_written += 1

    # --- Grammar errors -> persistent error taxonomy. ---
    errors_written = 0
    for err in state.get("grammar_errors", []):
        rule = err.get("rule") or "unknown"
        analytics.record_error(user_id, language, rule)
        errors_written += 1

    # --- Conversation turns -> session history. ---
    turns_written = session_history.record_turns(
        state["session_id"], user_id, language, state.get("messages", [])
    )

    # --- Session metrics -> analytics. ---
    analytics.log_session(
        user_id,
        language,
        session_type=state.get("mode", "conversation"),
        duration_minutes=duration_minutes,
        words_practiced=len(state.get("new_vocabulary", [])),
        new_words_learned=vocab_written,
        grammar_errors=errors_written,
        cefr_estimate=state.get("cefr_level"),
    )

    return {
        "vocabulary": vocab_written,
        "grammar_errors": errors_written,
        "turns": turns_written,
    }


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


async def finalize_session(
    state: LearnerState, *, duration_minutes: float = 0.0
) -> dict[str, Any]:
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
