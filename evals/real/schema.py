"""Versioned schemas for the real-model evaluation datasets.

A dataset is a set of *cases* (one learner text, or one exchange, plus its
labels), each carrying its own annotation provenance. Three rules shape the
schema:

- **Validation status is explicit.** ``expert_validated`` means at least one
  qualified human annotator labeled or reviewed the case. Cases written and
  labeled by the repository author — including an AI assistant — are
  ``author_labeled``; generated cases are ``synthetic``. Reports and quality
  gates read this field and never treat author-labeled or synthetic cases as
  expert-validated.
- **Acceptable alternatives are first-class.** An expected error lists every
  accepted correction and construction id, and correct texts list the
  alternative formulations that are also correct.
- **Splits are leakage-safe.** Cases share a ``group_id`` when they are
  variants of one item (a minimal pair, the same sentence with and without
  context); a whole group always lands in one split.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: Bump when a field is added/changed; stored in every manifest.
SCHEMA_VERSION = "1.0"

CEFR = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
Split = Literal["dev", "test"]
ValidationStatus = Literal["expert_validated", "author_labeled", "synthetic"]
AnnotatorType = Literal["expert", "trained_annotator", "author", "llm_assistant"]

#: What a grammar case tests. See ``datasets/RUBRIC.md`` for definitions.
GRAMMAR_CATEGORIES = (
    "correct",
    "incorrect",
    "vocabulary_misuse",
    "context_inappropriate",
    "acceptable_alternative",
    "regional",
    "formal",
    "informal",
    "ambiguous",
    "adversarial",
)
GrammarCategory = Literal[
    "correct",
    "incorrect",
    "vocabulary_misuse",
    "context_inappropriate",
    "acceptable_alternative",
    "regional",
    "formal",
    "informal",
    "ambiguous",
    "adversarial",
]
Difficulty = Literal["easy", "medium", "hard"]
ErrorSkill = Literal["grammar", "vocabulary", "pragmatics"]
#: Classifications of the production grammar taxonomy (src.llm.schemas).
Classification = Literal[
    "wrong", "awkward", "unusual", "regional", "formal", "informal", "acceptable"
]


class Annotation(BaseModel):
    """One annotator's judgment of a case."""

    annotator_id: str
    annotator_type: AnnotatorType
    #: The annotator's label: does the text contain an error a tutor should flag?
    #: ``None`` = genuinely ambiguous (either reading is defensible).
    has_error: bool | None
    rubric_version: str
    annotated_at: str
    notes: str = ""


class ExpectedError(BaseModel):
    """One error the text contains, with every accepted way to describe it."""

    #: The erroneous span as it appears in the text (exact substring).
    span: str
    #: Accepted corrections of the span (any of them is right).
    corrections: list[str] = Field(min_length=1)
    #: Accepted construction ids (normalized form), most canonical first.
    constructions: list[str] = Field(min_length=1)
    skill: ErrorSkill = "grammar"
    #: CEFR level of the construction itself (for difficulty classification).
    construction_cefr: CEFR | None = None


class GrammarCase(BaseModel):
    """One learner text for the grammar agent, with its labels and provenance."""

    case_id: str
    group_id: str
    language: str
    text: str
    #: The situation the text was produced in, when it matters (register cases).
    context: str | None = None
    category: GrammarCategory
    #: Proficiency level of the (simulated) learner who wrote the text.
    cefr_level: CEFR
    #: How hard the case is to judge correctly.
    difficulty: Difficulty
    #: Adjudicated label. ``None`` = ambiguous; abstaining is the right answer.
    has_error: bool | None
    expected_errors: list[ExpectedError] = Field(default_factory=list)
    #: For texts without an error: the taxonomy class a model may legitimately
    #: report it as (e.g. "regional" for voseo), besides reporting nothing.
    acceptable_classifications: list[Classification] = Field(default_factory=list)
    #: Other formulations that are also correct (documentation and synonyms).
    acceptable_variants: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    annotations: list[Annotation] = Field(min_length=1)
    validation_status: ValidationStatus
    source: str = "authored"
    split: Split | None = None
    rationale: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> GrammarCase:
        if self.has_error is True and not self.expected_errors:
            raise ValueError(f"{self.case_id}: has_error=True needs expected_errors")
        if self.has_error is not True and self.expected_errors:
            raise ValueError(f"{self.case_id}: only error cases list expected_errors")
        for e in self.expected_errors:
            if e.span not in self.text:
                raise ValueError(f"{self.case_id}: span {e.span!r} not in text")
        if self.category == "context_inappropriate" and not self.context:
            raise ValueError(f"{self.case_id}: context_inappropriate needs a context")
        if self.category == "ambiguous" and self.has_error is not None:
            raise ValueError(f"{self.case_id}: ambiguous cases have has_error=None")
        experts = [
            a for a in self.annotations if a.annotator_type in ("expert", "trained_annotator")
        ]
        if self.validation_status == "expert_validated" and not experts:
            raise ValueError(f"{self.case_id}: expert_validated needs an expert annotation")
        return self


class ExpectedWord(BaseModel):
    """A word the vocabulary agent should extract, with accepted glosses."""

    word: str
    #: Other accepted surface forms / lemmas (e.g. "sostener" for "sostienen").
    forms: list[str] = Field(default_factory=list)
    #: Accepted English translations (normalized comparison).
    translations: list[str] = Field(min_length=1)
    #: Whether the word occurs in the learner's own text.
    produced_by_learner: bool = False


class VocabularyCase(BaseModel):
    """One exchange for the vocabulary-extraction agent."""

    case_id: str
    group_id: str
    language: str
    cefr_level: CEFR
    difficulty: Difficulty
    user_text: str
    agent_text: str
    #: Words clearly above the learner's level that should be extracted.
    required_words: list[ExpectedWord] = Field(default_factory=list)
    #: Words it is fine (not required) to extract.
    optional_words: list[str] = Field(default_factory=list)
    #: Words the prompt says never to extract (basic words, names, numbers).
    forbidden_words: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    annotations: list[Annotation] = Field(min_length=1)
    validation_status: ValidationStatus
    source: str = "authored"
    split: Split | None = None

    @field_validator("required_words")
    @classmethod
    def _words_unique(cls, v: list[ExpectedWord]) -> list[ExpectedWord]:
        words = [w.word.lower() for w in v]
        if len(words) != len(set(words)):
            raise ValueError("duplicate required word")
        return v


class DatasetManifest(BaseModel):
    """Identity and integrity record of one dataset version."""

    dataset: str
    version: str
    schema_version: str
    rubric_version: str
    task: Literal["grammar", "vocabulary"]
    created: str
    languages: list[str]
    counts: dict[str, int]
    validation_status_counts: dict[str, int]
    #: Published file name -> sha256 of its bytes.
    files: dict[str, str]
    split_rule: str
    provenance: str
    known_limitations: list[str] = Field(default_factory=list)
