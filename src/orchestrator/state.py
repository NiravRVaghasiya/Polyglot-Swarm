"""LangGraph state definition for the learning session."""

from operator import add
from typing import Annotated, Any, NotRequired, TypedDict


class GrammarError(TypedDict):
    """A detected grammar error."""

    original: str
    correction: str
    rule: str
    explanation: str
    severity: str  # "minor", "moderate", "critical"
    # Phase 4 taxonomy (optional; consumers read via .get with defaults).
    classification: NotRequired[str]  # wrong|awkward|regional|informal|acceptable|...
    construction: NotRequired[str]
    confidence: NotRequired[float]
    alternatives: NotRequired[list[str]]


class VocabularyItem(TypedDict):
    """A vocabulary item tracked during conversation."""

    word: str
    translation: str
    pos: str  # part of speech
    context_sentence: str
    is_new: bool


class LearnerState(TypedDict):
    """Shared state flowing through the LangGraph agent graph.

    This state is checkpointed after every node execution,
    enabling session persistence and recovery.
    """

    # --- Session metadata ---
    session_id: str
    user_id: str  # Owner of the session; keys all persisted memory
    language: str  # Free-form language name (e.g., "Spanish", "Japanese", "Arabic")
    mode: str  # "conversation", "review", "drill", "assessment"
    # The interaction id the current turn is running under (Phase 17
    # observability); set by src.api.sessions.run_turn from the contextvar so
    # anything reading state directly can also correlate to it.
    interaction_id: NotRequired[str]

    # --- Conversation ---
    messages: Annotated[list[dict[str, Any]], add]  # Chat history (appended via reducer)
    current_scenario: dict[str, Any] | None
    current_persona: str | None

    # --- Agent outputs (per turn) ---
    grammar_errors: list[GrammarError]
    new_vocabulary: list[VocabularyItem]
    cultural_notes: list[str]
    evaluation: dict[str, Any] | None  # Evaluator Agent output
    transfer_suggestions: list[dict[str, Any]]  # Cross-Language Transfer Agent output

    # --- Persistent learner profile ---
    cefr_level: str  # "A1", "A2", "B1", "B2", "C1", "C2"
    vocabulary_known_count: int
    grammar_weaknesses: list[str]  # e.g., ["ser_vs_estar", "subjunctive"]
    user_interests: list[str]

    # --- Control flow ---
    turn_count: int
    should_end_session: bool
    pending_reviews: list[dict[str, Any]]  # FSRS items due for review
    last_user_input: str
    agent_response: str  # Final response to show user
