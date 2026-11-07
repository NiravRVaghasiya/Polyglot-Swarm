"""Extraction — turn the raw outputs of a session into evidence events.

The orchestrator accumulates per-turn agent outputs on the ``LearnerState``:
``grammar_errors``, ``new_vocabulary``, and conversation ``messages``. This
module maps those into structured :class:`LearningEvent` records with the right
type, competence target (skill/subskill/objective/item), task type and
difficulty, assessment, reliability, and provenance (source plus prompt and
rubric versions) — the raw material the belief layer is then derived from.

Two distinctions matter to the learner model (ADR-0031):

- A word the vocabulary agent lists is only *produced* evidence when it occurs
  in the learner's own text. Words it picked out of the tutor's reply are
  exposure (``VOCAB_OBSERVED``): they count as practised, never as mastery.
- Several judgments of the same learner production share a ``correlation_id``
  so they are not counted as independent observations.

It deliberately does NOT touch storage or the learner model; it is a pure
transform (state -> events) so it is trivially testable and reusable by the
CLI, API, and future voice pipeline.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.evidence import confidence
from src.evidence.difficulty import cefr_to_difficulty
from src.evidence.events import DifficultyBasis, EventType, LearningEvent
from src.evidence.normalizer import normalize_rule, normalize_word
from src.evidence.provenance import Provenance

#: Source tag for evidence this module produces (bumped with ADR-0031).
SOURCE = "session-extractor-v2"
#: The grading scheme grammar judgments follow (ADR-0007 taxonomy).
GRAMMAR_RUBRIC = "grammar-taxonomy-v1"

# Session mode -> the task type its evidence comes from.
_TASK_TYPE_BY_MODE: dict[str, str] = {
    "conversation": "free_conversation",
    "scenario": "scenario_roleplay",
    "review": "review_recall",
    "drill": "drill",
    "writing": "writing",
}

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def task_type_for_mode(mode: str | None) -> str:
    """Return the evidence task type for a session mode (unknown modes pass through)."""
    if not mode:
        return "free_conversation"
    return _TASK_TYPE_BY_MODE.get(mode, mode)


def _prompt_version(name: str) -> str | None:
    try:
        from src.llm.prompts.registry import prompt_version

        return f"{name}@{prompt_version(name)}"
    except Exception:  # noqa: BLE001 - provenance enrichment must never break extraction
        return None


def correlation_key(session_id: str | None, production: str | None) -> str | None:
    """A stable id for "this learner production in this session".

    Judgments of the same production (e.g. the grammar agent and the writing
    agent both flagging one sentence) share it. ``None`` when there is no
    production text to key on.
    """
    if not production:
        return None
    text = " ".join(production.split()).lower()
    digest = hashlib.sha256(f"{session_id or ''}|{text}".encode()).hexdigest()
    return digest[:24]


def _construction_difficulty(language: str, construction: str) -> float | None:
    try:
        from src.languages.grammar_taxonomy import get_construction

        item = get_construction(language, construction)
    except Exception:  # noqa: BLE001 - an unreadable pack just means unknown difficulty
        return None
    return cefr_to_difficulty(item.cefr) if item is not None else None


def extract_grammar_events(
    user_id: str,
    language: str,
    grammar_errors: list[dict[str, Any]],
    *,
    provenance: Provenance,
    task_type: str | None = None,
) -> list[LearningEvent]:
    """One GRAMMAR_ERROR event per detected error.

    The event's ``assessment`` reflects the Phase 4 taxonomy classification
    (``wrong``/``awkward``/...) rather than a hardcoded ``incorrect``, and its
    confidence comes from the agent's calibrated value when present. The
    construction id (preferred) or rule becomes the ``item_id`` and
    ``subskill``; its language-pack CEFR level, when the pack has it, becomes
    the task difficulty (basis ``cefr_label``).
    """
    if provenance.prompt_version is None or provenance.rubric_version is None:
        provenance = Provenance(
            source=provenance.source,
            session_id=provenance.session_id,
            interaction_id=provenance.interaction_id,
            model_version=provenance.model_version,
            rubric_version=provenance.rubric_version or GRAMMAR_RUBRIC,
            prompt_version=provenance.prompt_version or _prompt_version("grammar"),
        )
    events: list[LearningEvent] = []
    for err in grammar_errors:
        construction = err.get("construction") or err.get("rule") or "unknown"
        canonical = normalize_rule(construction)
        severity = err.get("severity")
        classification = (err.get("classification") or "wrong").lower()
        conf = confidence.score(
            EventType.GRAMMAR_ERROR,
            provided=err.get("confidence"),
            severity=severity,
        )
        difficulty = _construction_difficulty(language, canonical)
        events.append(
            LearningEvent.create(
                EventType.GRAMMAR_ERROR,
                user_id,
                language,
                provenance=provenance,
                item_id=construction,
                subskill=canonical,
                objective_id=f"grammar.{canonical}",
                task_type=task_type,
                difficulty=difficulty,
                difficulty_basis=DifficultyBasis.CEFR_LABEL if difficulty is not None else None,
                correlation_id=correlation_key(provenance.session_id, err.get("original")),
                observed=err.get("original"),
                expected=err.get("correction"),
                # "wrong" -> "incorrect" so the belief layer / analytics keep
                # their existing semantics; other classifications flow through.
                assessment="incorrect" if classification == "wrong" else classification,
                confidence=conf,
                payload={
                    "explanation": err.get("explanation", ""),
                    "severity": severity or "moderate",
                    "classification": classification,
                    "alternatives": err.get("alternatives", []),
                },
            )
        )
    return events


def _learner_tokens(messages: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for msg in messages:
        if msg.get("role") == "user" and msg.get("content"):
            tokens.update(t.lower() for t in _TOKEN_RE.findall(str(msg["content"])))
    return tokens


def _produced_by_learner(word: str, learner_tokens: set[str]) -> bool:
    parts = [t.lower() for t in _TOKEN_RE.findall(word)]
    return bool(parts) and all(p in learner_tokens for p in parts)


def extract_vocabulary_events(
    user_id: str,
    language: str,
    new_vocabulary: list[dict[str, Any]],
    *,
    provenance: Provenance,
    messages: list[dict[str, Any]] | None = None,
    task_type: str | None = None,
) -> list[LearningEvent]:
    """One vocabulary event per new word encountered in the turn.

    With ``messages`` given, a word that occurs in the learner's own turns is
    ``VOCAB_PRODUCED`` (weak positive evidence of productive knowledge); any
    other word is ``VOCAB_OBSERVED`` (exposure from the tutor's reply). Without
    ``messages`` the legacy behaviour applies: every word is ``VOCAB_PRODUCED``.
    """
    if provenance.prompt_version is None:
        provenance = Provenance(
            source=provenance.source,
            session_id=provenance.session_id,
            interaction_id=provenance.interaction_id,
            model_version=provenance.model_version,
            rubric_version=provenance.rubric_version,
            prompt_version=_prompt_version("vocabulary"),
        )
    learner_tokens = _learner_tokens(messages) if messages is not None else None
    events: list[LearningEvent] = []
    for item in new_vocabulary:
        word = item.get("word")
        if not word:
            continue
        produced = learner_tokens is None or _produced_by_learner(word, learner_tokens)
        event_type = EventType.VOCAB_PRODUCED if produced else EventType.VOCAB_OBSERVED
        dimension = "production" if produced else "exposure"
        events.append(
            LearningEvent.create(
                event_type,
                user_id,
                language,
                provenance=provenance,
                item_id=word,
                subskill=dimension,
                objective_id=f"vocabulary.{dimension}",
                task_type=task_type,
                observed=word,
                assessment="observed" if produced else "exposed",
                confidence=confidence.score(event_type),
                payload={
                    "translation": item.get("translation", ""),
                    "pos": item.get("pos", ""),
                    "context_sentence": item.get("context_sentence", ""),
                    "lemma": normalize_word(word),
                },
            )
        )
    return events


def extract_turn_events(
    user_id: str,
    language: str,
    messages: list[dict[str, Any]],
    *,
    provenance: Provenance,
    task_type: str | None = None,
) -> list[LearningEvent]:
    """One TURN_COMPLETED event per user turn (the learner's own production).

    Turns are practice, not graded evidence: the learner model counts them
    toward coverage, not mastery.
    """
    events: list[LearningEvent] = []
    for msg in messages:
        if msg.get("role") != "user" or not msg.get("content"):
            continue
        events.append(
            LearningEvent.create(
                EventType.TURN_COMPLETED,
                user_id,
                language,
                provenance=provenance,
                task_type=task_type,
                observed=msg["content"],
                confidence=confidence.score(EventType.TURN_COMPLETED),
            )
        )
    return events


def extract_from_state(state: dict[str, Any]) -> list[LearningEvent]:
    """Extract all events from a completed session's ``LearnerState``.

    Reads ``grammar_errors``, ``new_vocabulary``, and ``messages`` from the
    state dict. Provenance is stamped from the session id; the task type comes
    from the session mode.
    """
    user_id = state["user_id"]
    language = state["language"]
    session_id = state.get("session_id")
    # Which models produced the judgments (a fallback model is marked as such),
    # so evidence quality stays traceable when providers fail over (ADR-0035).
    models = state.get("llm_models") or []
    provenance = Provenance(
        source=SOURCE, session_id=session_id, model_version=", ".join(models) or None
    )
    task_type = task_type_for_mode(state.get("mode"))
    messages = state.get("messages", [])

    events: list[LearningEvent] = []
    events += extract_turn_events(
        user_id, language, messages, provenance=provenance, task_type=task_type
    )
    events += extract_grammar_events(
        user_id,
        language,
        state.get("grammar_errors", []),
        provenance=provenance,
        task_type=task_type,
    )
    events += extract_vocabulary_events(
        user_id,
        language,
        state.get("new_vocabulary", []),
        provenance=provenance,
        messages=messages,
        task_type=task_type,
    )
    return events
