"""Seeded learner-state cases for the planner (the adaptive engine).

Each case describes what to seed into storage (due vocabulary, grammar error
evidence, skill beliefs) for one synthetic learner, and which targets the
resulting plan (:func:`src.adaptive.service.recommend`) must cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Bump when cases are added/changed/removed.
DATASET_VERSION = "2026.11.1"


@dataclass(frozen=True)
class CoverageCase:
    """A learner state seeded with due reviews and/or grammar weaknesses.

    ``expected_targets`` are recommendation ``target`` values (words or
    construction ids) the plan must contain — the "target coverage" property:
    things the learner is overdue on, or weak in, must show up as
    recommendations.

    Grammar errors are seeded as ``GRAMMAR_ERROR`` evidence events, one per
    session, as conversation finalization records them; constructions must be
    in the language pack, since the planner only plans catalog objectives.

    The gated budget is generous (60 minutes, up to 10 activities), as for
    :class:`SkillBalanceCase`: for a learner with no other evidence the
    engine also schedules assessments and an introduction, which can push a
    B1/B2 remediation past a 15-minute plan. The suite reports coverage at
    the UI's 15-minute default too, ungated, so that ranking stays visible.
    """

    name: str
    user_id: str
    due_words: tuple[str, ...] = ()
    grammar_errors: tuple[tuple[str, int], ...] = ()  # (construction, occurrences)
    expected_targets: frozenset[str] = field(default_factory=frozenset)
    time_available_minutes: float = 60.0
    max_actions: int = 10


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
        name="b1_contrast_weakness",
        user_id="eval-coverage-contrast",
        grammar_errors=(("por_vs_para", 3),),
        expected_targets=frozenset({"por_vs_para"}),
    ),
    CoverageCase(
        name="mixed_review_and_grammar",
        user_id="eval-coverage-mixed",
        due_words=("hambre",),
        grammar_errors=(("subjunctive_present", 4),),
        expected_targets=frozenset({"hambre", "subjunctive_present"}),
    ),
]


@dataclass(frozen=True)
class SkillBalanceCase:
    """A learner whose weakest skill (via seeded evidence) should drive the plan.

    ``events`` are ``(skill, assessment, count)`` triples applied through the
    knowledge model as ``count`` observations of *distinct* items, mirroring
    how real evidence accumulates skill beliefs (ADR-0031: repeats of one
    identical observation count once).
    A skill is skipped when the evidence shows one of its prerequisites is
    weak (unassessed prerequisites no longer block, ADR-0031), so each case
    also seeds passing evidence for its skill's prerequisites, not just the
    target skill itself. ``time_available_minutes`` is generous (60 rather than the
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
