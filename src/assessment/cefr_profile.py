"""Multidimensional CEFR profile: per-skill band + confidence + sample size.

Builds a CEFR profile from the learner knowledge model's per-skill beliefs
(mastery/uncertainty/sample_size) rather than collapsing competence to a single
number. Each skill maps to a CEFR band via a mastery→band curve; the model's
uncertainty and how much evidence backs it become a reported confidence and
sample size. The overall band is a conservative aggregate.

This is the plan's Phase 12: CEFR as a multidimensional profile with confidence,
persisted to the ``assessments`` store for later validation against expert
ratings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.learner import get_knowledge_model
from src.memory import assessments

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

#: Method tag written to the assessments store (versioned).
METHOD = "cefr-profile-v1"

# Mastery in [0, 1] -> CEFR band. Each band spans a mastery range; the curve is
# deliberately conservative (needs high mastery for the top bands).
_MASTERY_BANDS: list[tuple[float, str]] = [
    (0.15, "A1"),
    (0.35, "A2"),
    (0.55, "B1"),
    (0.75, "B2"),
    (0.90, "C1"),
]


def mastery_to_cefr(mastery: float) -> str:
    """Map a mastery score in [0, 1] to a CEFR band (A1..C2)."""
    mastery = max(0.0, min(1.0, mastery))
    for bound, level in _MASTERY_BANDS:
        if mastery < bound:
            return level
    return "C2"


def _min_level(levels: list[str], *, default: str = "A1") -> str:
    """Return the lowest CEFR band among ``levels`` (conservative overall)."""
    if not levels:
        return default
    return min(levels, key=lambda lvl: CEFR_ORDER.index(lvl))


def confidence_from(uncertainty: float, sample_size: float) -> float:
    """Combine model uncertainty and evidence volume into a confidence in [0, 1].

    Low uncertainty and more observations both raise confidence. With no
    evidence, confidence is ~0.
    """
    from_unc = 1.0 - max(0.0, min(1.0, uncertainty))
    # Saturating evidence factor: ~0.5 at 5 obs, ~0.9 at ~45 obs.
    from_n = sample_size / (sample_size + 5.0) if sample_size > 0 else 0.0
    return round(max(0.0, min(1.0, 0.5 * from_unc + 0.5 * from_n)), 3)


@dataclass
class SkillAssessment:
    """One skill's CEFR estimate with its confidence and evidence."""

    skill: str
    cefr: str
    mastery: float
    confidence: float
    sample_size: int


@dataclass
class CEFRProfile:
    """A learner's multidimensional CEFR profile for one language."""

    language: str
    overall: str
    skills: dict[str, SkillAssessment] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "overall": self.overall,
            "skills": {
                s: {
                    "cefr": a.cefr,
                    "mastery": round(a.mastery, 3),
                    "confidence": a.confidence,
                    "sample_size": a.sample_size,
                }
                for s, a in self.skills.items()
            },
        }


def build_cefr_profile(
    user_id: str,
    language: str,
    *,
    fallback_cefr: str = "A2",
) -> CEFRProfile:
    """Build a per-skill CEFR profile from the learner knowledge model.

    Reads the model's per-skill beliefs; a skill with no belief is omitted. The
    overall band is the conservative minimum across skills (falls back to
    ``fallback_cefr`` when the learner has no beliefs yet).
    """
    beliefs = get_knowledge_model().current_beliefs(user_id, language)

    skills: dict[str, SkillAssessment] = {}
    for skill, belief in beliefs.items():
        skills[skill] = SkillAssessment(
            skill=skill,
            cefr=mastery_to_cefr(belief.mastery),
            mastery=belief.mastery,
            confidence=confidence_from(belief.uncertainty, belief.sample_size),
            sample_size=int(round(belief.sample_size)),
        )

    overall = _min_level([a.cefr for a in skills.values()], default=fallback_cefr)
    return CEFRProfile(language=language, overall=overall, skills=skills)


def persist_profile(user_id: str, profile: CEFRProfile) -> int:
    """Persist a CEFR profile to the assessments store.

    Writes one row per skill (with confidence + sample size) plus one overall
    row (``skill=None``). Returns the number of rows written.
    """
    written = 0
    for skill, a in profile.skills.items():
        assessments.record_assessment(
            user_id,
            profile.language,
            skill=skill,
            cefr=a.cefr,
            score=a.mastery,
            confidence=a.confidence,
            sample_size=a.sample_size,
            method=METHOD,
        )
        written += 1

    # Overall row (skill=None). Confidence/sample are aggregated conservatively.
    overall_conf = min((a.confidence for a in profile.skills.values()), default=0.0)
    overall_n = sum(a.sample_size for a in profile.skills.values())
    assessments.record_assessment(
        user_id,
        profile.language,
        skill=None,
        cefr=profile.overall,
        confidence=overall_conf,
        sample_size=overall_n,
        method=METHOD,
    )
    written += 1
    return written
