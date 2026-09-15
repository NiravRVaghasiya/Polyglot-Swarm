"""Pydantic schemas for structured LLM output + a tolerant parse helper.

The plan (Phase 1) requires LLM output to be structured and schema validated,
and (Phase 9) that the system can *abstain* when uncertain rather than emit a
malformed or low-confidence result. This module provides:

- reusable response models (grammar analysis, vocabulary extraction, ingestion,
  and a generic verifier decision with an ``abstain`` option),
- :func:`parse_structured`, which strips markdown code fences, ``json.loads``,
  and validates against a model — returning ``None`` on any failure instead of
  raising, so callers degrade gracefully.

Agents can adopt these incrementally: today they hand-parse JSON; ``provider.
generate_structured`` and these models give them a validated path without
changing the wire format.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("polyglot.llm.schemas")


# --------------------------------------------------------------------------- #
# Response models
# --------------------------------------------------------------------------- #


# Classification of a detected deviation (Phase 4). Only ``wrong`` (and, weakly,
# ``awkward``) are genuine errors; the rest are acceptable variation the tutor
# must not "correct". This is distinct from ``severity`` (how bad an actual
# error is).
GRAMMAR_CLASSIFICATIONS = (
    "wrong",  # genuinely incorrect
    "awkward",  # understandable but non-idiomatic
    "unusual",  # rare but valid
    "regional",  # valid in some dialect/region
    "formal",  # valid, more formal register
    "informal",  # valid, more casual register
    "acceptable",  # a fully acceptable alternative — not an error
)

#: Which classifications count as a genuine error worth surfacing/persisting.
ERROR_CLASSIFICATIONS = frozenset({"wrong", "awkward"})


class GrammarErrorModel(BaseModel):
    """A single detected grammar deviation (validated form of the wire dict).

    Extends the legacy five-field error with a Phase 4 taxonomy: a
    ``classification`` (wrong/awkward/regional/informal/acceptable/...), the
    ``construction`` it concerns, acceptable ``alternatives``, and a calibrated
    ``confidence``. The legacy keys (original/correction/rule/explanation/
    severity) are preserved so downstream consumers keep working.
    """

    original: str
    correction: str = ""
    rule: str = "unknown"
    explanation: str = ""
    severity: str = "moderate"  # minor | moderate | critical
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Phase 4 taxonomy (all optional/defaulted for backward-compat).
    classification: str = "wrong"
    construction: str = ""  # canonical construction id; falls back to ``rule``
    alternatives: list[str] = Field(default_factory=list)

    def is_error(self) -> bool:
        """Whether this deviation is a genuine error worth surfacing."""
        return self.classification.lower() in ERROR_CLASSIFICATIONS


class GrammarAnalysis(BaseModel):
    """The grammar agent's structured response."""

    errors: list[GrammarErrorModel] = Field(default_factory=list)


class GrammarItem(BaseModel):
    """A grammar construction in the taxonomy (a teachable unit).

    Mirrors the plan's ``grammar_item``: a language-specific construction with
    its CEFR level, an explanation, examples, prerequisite constructions, and
    common cross-language interferences that trigger it.
    """

    language: str
    construction: str
    cefr: str = "A1"
    explanation: str = ""
    examples: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    common_interferences: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Language-pack models (Phase 10)
# --------------------------------------------------------------------------- #


class CollocationItem(BaseModel):
    """A fixed multi-word lexical unit from a language pack."""

    phrase: str
    translation: str = ""
    pattern: str = ""  # e.g. "verb + noun"
    cefr: str = "A1"
    # ``register_label`` avoids shadowing a pydantic BaseModel attribute; the
    # pack YAML still uses the natural ``register`` key via the alias.
    register_label: str = Field(default="neutral", alias="register")

    model_config = {"populate_by_name": True}


class RegisterNote(BaseModel):
    """A note about register/formality usage in a language."""

    topic: str  # e.g. "tú vs usted"
    note: str
    register_label: str = Field(default="neutral", alias="register")

    model_config = {"populate_by_name": True}


class LanguageMetadata(BaseModel):
    """Top-level metadata for a language pack (``metadata.yaml``)."""

    language: str
    code: str = ""
    family: str = ""  # e.g. "Romance", "Slavic", "Japonic"
    dialect: str = ""
    writing_system: str = "Latin"
    notes: str = ""


class LanguagePack(BaseModel):
    """A fully assembled language pack: metadata + linguistic resources.

    Generic agent infrastructure stays reusable; language-specific knowledge is
    explicit and version-controlled under ``languages/<code>/``. Missing
    resources default to empty, so a partial pack still loads.
    """

    metadata: LanguageMetadata
    # Frequency-ranked words (index 0 = most frequent). Rank is 1-based.
    frequency: list[str] = Field(default_factory=list)
    collocations: list[CollocationItem] = Field(default_factory=list)
    register_notes: list[RegisterNote] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Cross-language transfer (Phase 11)
# --------------------------------------------------------------------------- #

# Kinds of transfer relation between a source word/construction and a target
# language. Positive transfer helps; negative transfer (false friends,
# interference) is a trap to warn about.
TRANSFER_RELATIONS = (
    "cognate",  # positive: same root, same meaning (familia -> famiglia)
    "false_friend",  # negative: looks similar, different meaning
    "shared_construction",  # positive: same grammatical construction
    "interference",  # negative: a source pattern that misfires in the target
    "pronunciation",  # a pronunciation carryover to watch
)


class TransferEdge(BaseModel):
    """One transfer relation from a source item to a target language.

    Retrieved from the language-pack transfer resources as a *candidate*; an LLM
    verification pass (Phase 11) confirms or drops it before it reaches the
    learner, so the tutor does not assert an invented cognate.
    """

    source_word: str
    target_language: str
    target_word: str = ""
    relation: str = "cognate"  # one of TRANSFER_RELATIONS
    note: str = ""  # warning for false friends / interference; hint otherwise

    def is_positive(self) -> bool:
        """Whether this relation is positive transfer (helps the learner)."""
        return self.relation in ("cognate", "shared_construction")


class VocabularyItemModel(BaseModel):
    """A single extracted vocabulary item."""

    word: str
    translation: str = ""
    pos: str = "unknown"
    context_sentence: str = ""


class VocabularyExtraction(BaseModel):
    """The vocabulary agent's structured response."""

    words: list[VocabularyItemModel] = Field(default_factory=list)


class IngestionVocab(BaseModel):
    """One harvested word from ingested content."""

    word: str
    translation: str = ""
    pos: str = ""


class IngestionResult(BaseModel):
    """The ingestion agent's structured response."""

    simplified: str = ""
    vocab: list[IngestionVocab] = Field(default_factory=list)


class VerifierDecision(BaseModel):
    """An evaluator/verifier decision, supporting explicit abstention.

    ``decision`` is one of accept | revise | reject | abstain. Abstention is a
    first-class outcome (Phase 9): a tutor that says "I'm not confident" beats
    one that confidently teaches wrong language.
    """

    decision: str = "accept"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    revised: str | None = None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def strip_code_fences(text: str) -> str:
    """Return the inner content of a ```` ``` ````-fenced block, if present.

    LLMs frequently wrap JSON in markdown fences despite instructions not to.
    This mirrors the ad-hoc stripping the agents already do, centralized.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            if inner.startswith("json"):
                inner = inner[4:]
            return inner.strip()
    return stripped


def parse_structured[T: BaseModel](text: str, model: type[T]) -> T | None:
    """Parse and validate ``text`` into ``model``; return ``None`` on failure.

    Tolerates markdown code fences. Never raises: a malformed or schema-invalid
    response yields ``None`` so callers can fall back to a safe default (an
    empty result, or abstaining).
    """
    try:
        data = json.loads(strip_code_fences(text))
    except (json.JSONDecodeError, TypeError):
        logger.debug("structured parse: invalid JSON for %s", model.__name__)
        return None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        logger.debug("structured parse: schema validation failed for %s: %s", model.__name__, exc)
        return None
