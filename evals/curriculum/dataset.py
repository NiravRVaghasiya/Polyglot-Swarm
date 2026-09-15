"""Seeded learner-state cases for the curriculum planner.

Each case describes what to seed into storage (due vocabulary, grammar error
patterns, skill beliefs) for one synthetic learner, and which action targets
the resulting plan (:func:`src.curriculum.plan_next_actions`) must cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bump when cases are added/changed/removed.
DATASET_VERSION = "2026.09.0"


@dataclass(frozen=True)
class CoverageCase:
    """A learner state seeded with due reviews and/or grammar weaknesses.

    ``expected_targets`` are action ``target`` values (words or construction
    ids) the plan must contain at least one action for — this is the "target
    coverage" property: things the learner is overdue on, or weak in, must
    show up as recommendations.
    """

    name: str
    user_id: str
    due_words: tuple[str, ...] = ()
    grammar_errors: tuple[tuple[str, int], ...] = ()  # (construction, occurrences)
    expected_targets: frozenset[str] = field(default_factory=frozenset)


COVERAGE_CASES: list[CoverageCase] = [
    CoverageCase(
        name="overdue_vocabulary",
        user_id="eval-coverage-vocab",
        due_words=("mesa", "silla", "ventana"),
        expected_targets=frozenset({"mesa", "silla", "ventana"}),
    ),
    CoverageCase(
        name="recurring_grammar_weakness",
        user_id="eval-coverage-grammar",
        grammar_errors=(("ser_vs_estar", 5),),
        expected_targets=frozenset({"ser_vs_estar"}),
    ),
    CoverageCase(
        name="vs_construction_becomes_contrast",
        user_id="eval-coverage-contrast",
        grammar_errors=(("por_vs_para", 3),),
        expected_targets=frozenset({"por_vs_para"}),
    ),
    CoverageCase(
        name="mixed_review_and_grammar",
        user_id="eval-coverage-mixed",
        due_words=("hambre",),
        grammar_errors=(("subjunctive_trigger", 4),),
        expected_targets=frozenset({"hambre", "subjunctive_trigger"}),
    ),
]


@dataclass(frozen=True)
class SkillBalanceCase:
    """A learner whose weakest skill (via seeded evidence) should drive the plan.

    ``events`` are ``(skill, assessment, count)`` triples applied through the
    knowledge model, mirroring how real evidence accumulates skill beliefs.
    Every skill the planner proposes must be "ready" per
    :func:`src.learner.skill_graph.is_ready` (its prerequisites at or above
    0.4 mastery) or it is filtered out before scoring — so each case also
    seeds a passing score for its skill's prerequisites, not just the target
    skill itself. ``time_available_minutes`` is generous (60 rather than the
    15-minute default) so a lower-priority but still-relevant action for the
    target skill isn't squeezed out of the plan purely by the time budget.
    """

    name: str
    user_id: str
    events: tuple[tuple[str, str, int], ...]
    expected_skill_in_plan: str
    time_available_minutes: float = 60.0
    #: Generous by default: with several prerequisite skills also well
    #: evidenced (e.g. writing's grammar/spelling), those legitimately
    #: outrank the target skill on priority once their own uncertainty drops,
    #: so the default cap of 5 actions can truncate the target out — this
    #: reflects the planner's real ranking, not an eval artifact.
    max_actions: int = 10


SKILL_BALANCE_CASES: list[SkillBalanceCase] = [
    SkillBalanceCase(
        name="weak_listening",
        user_id="eval-balance-listening",
        # listening's only prerequisite is vocabulary.
        events=(("listening", "incorrect", 6), ("vocabulary", "correct", 6)),
        expected_skill_in_plan="listening",
    ),
    SkillBalanceCase(
        name="weak_writing",
        user_id="eval-balance-writing",
        # writing needs vocabulary + grammar + spelling all ready.
        events=(
            ("writing", "incorrect", 6),
            ("vocabulary", "correct", 6),
            ("grammar", "correct", 6),
            ("spelling", "correct", 6),
        ),
        expected_skill_in_plan="writing",
    ),
    SkillBalanceCase(
        name="weak_reading",
        user_id="eval-balance-reading",
        # reading's only prerequisite is vocabulary.
        events=(("reading", "incorrect", 6), ("vocabulary", "correct", 6)),
        expected_skill_in_plan="reading",
    ),
]


@dataclass(frozen=True)
class DifficultyCase:
    """A (mastery, fatigue) pair with the expected appropriateness verdict.

    Exercises :func:`src.curriculum.difficulty.difficulty_appropriate` directly
    — a pure function, so this is scored exactly rather than approximated.
    """

    name: str
    mastery: float
    fatigue: float
    expected_appropriate: bool


DIFFICULTY_CASES: list[DifficultyCase] = [
    DifficultyCase("mid_mastery_no_fatigue", mastery=0.5, fatigue=0.0, expected_appropriate=True),
    DifficultyCase("mastered_item", mastery=0.97, fatigue=0.0, expected_appropriate=False),
    DifficultyCase(
        "hard_item_while_fatigued", mastery=0.2, fatigue=0.8, expected_appropriate=False
    ),
    DifficultyCase("hard_item_while_fresh", mastery=0.2, fatigue=0.0, expected_appropriate=True),
    DifficultyCase(
        "moderate_item_while_fatigued", mastery=0.5, fatigue=0.8, expected_appropriate=True
    ),
]
