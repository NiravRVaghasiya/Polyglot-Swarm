"""Assessment — multidimensional CEFR profiling (Phase 12).

CEFR is treated as a multidimensional profile, not a single number: each skill
(speaking, listening, reading, writing, grammar, vocabulary, pragmatics) gets
its own band, with a confidence and a sample size, so progress can be shown as

    Speaking   B1- ± 0.3   (184 observations, medium confidence)

The profile is derived from the learner knowledge model's per-skill beliefs and
persisted to the ``assessments`` store, ready to be validated against expert
ratings later (the plan's Phase 12 validation).
"""

from src.assessment.cefr_profile import (
    CEFRProfile,
    SkillAssessment,
    build_cefr_profile,
    mastery_to_cefr,
    persist_profile,
)

__all__ = [
    "CEFRProfile",
    "SkillAssessment",
    "build_cefr_profile",
    "mastery_to_cefr",
    "persist_profile",
]
