"""Multidimensional CEFR profile with explicit evidence states (ADR-0015, ADR-0031).

Builds a CEFR profile from the learner knowledge model's evidence-derived
per-skill estimates (:class:`~src.learner.estimation.SkillEstimate`). Each skill
is estimated independently and carries a status:

- ``insufficient_evidence`` — no band is reported (``cefr`` is ``None``);
- ``provisional`` — a band from limited evidence (few observations/items, or a
  wide interval);
- ``estimated`` — enough independent, diverse evidence across sessions;
- ``validated`` — estimated *and* backed by a validated instrument (no producer
  in the app emits such evidence yet).

There is **no default level**: a new learner's profile has ``overall=None`` with
status ``insufficient_evidence``. The overall band is reported only when at
least :data:`MIN_SKILLS_FOR_OVERALL` skills are provisional or better, and is the
conservative minimum of their bands; its status is the weakest of theirs.
Skills without evidence are listed as unassessed, never scored as zero.

``confidence`` on each skill is the model's *evidence index* — an ordinal
evidence-sufficiency score in [0, 1], **not** a calibrated probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.learner import get_knowledge_model
from src.learner.cefr_bands import CEFR_ORDER, MASTERY_BANDS, mastery_to_cefr
from src.learner.estimation import EvidenceStatus, SkillEstimate, status_rank
from src.memory import assessments
from src.memory.skill_state import SKILLS

__all__ = [
    "CEFR_ORDER",
    "METHOD",
    "MIN_SKILLS_FOR_OVERALL",
    "CEFRProfile",
    "SkillAssessment",
    "build_cefr_profile",
    "confidence_from",
    "mastery_to_cefr",
    "persist_profile",
    "profile_from_estimates",
]

#: Method tag written to the assessments store (versioned).
METHOD = "cefr-profile-v2"

#: How many skills must be provisional or better before an overall band is given.
MIN_SKILLS_FOR_OVERALL = 2

# Kept for callers that imported the private name.
_MASTERY_BANDS = MASTERY_BANDS


def _min_level(levels: list[str]) -> str | None:
    """Return the lowest CEFR band among ``levels``, or ``None`` if empty."""
    if not levels:
        return None
    return min(levels, key=lambda lvl: CEFR_ORDER.index(lvl))


def confidence_from(uncertainty: float, sample_size: float) -> float:
    """Legacy (``cefr-profile-v1``) confidence heuristic, kept for comparison.

    Combines model uncertainty and raw evidence volume into a score in [0, 1].
    It counts raw (possibly duplicate) observations and is not calibrated; the
    v2 profile reports the engine's evidence index instead.
    """
    from_unc = 1.0 - max(0.0, min(1.0, uncertainty))
    # Saturating evidence factor: ~0.5 at 5 obs, ~0.9 at ~45 obs.
    from_n = sample_size / (sample_size + 5.0) if sample_size > 0 else 0.0
    return round(max(0.0, min(1.0, 0.5 * from_unc + 0.5 * from_n)), 3)


@dataclass
class SkillAssessment:
    """One skill's CEFR estimate with its evidence state."""

    skill: str
    cefr: str | None
    mastery: float | None
    #: Evidence index in [0, 1] (ordinal, not a probability).
    confidence: float
    #: Raw graded observations (duplicates included).
    sample_size: int
    status: str = EvidenceStatus.INSUFFICIENT.value
    mastery_low: float | None = None
    mastery_high: float | None = None
    uncertainty: float = 1.0
    independent_count: int = 0
    distinct_items: int = 0
    confidence_label: str = "none"
    coverage: dict[str, Any] = field(default_factory=dict)
    baseline_mastery: float | None = None

    @classmethod
    def from_estimate(cls, e: SkillEstimate) -> SkillAssessment:
        return cls(
            skill=e.skill,
            cefr=e.cefr,
            mastery=e.mastery,
            confidence=round(e.evidence_index, 3),
            sample_size=e.graded_count,
            status=e.status,
            mastery_low=e.mastery_low,
            mastery_high=e.mastery_high,
            uncertainty=e.uncertainty,
            independent_count=e.independent_count,
            distinct_items=e.distinct_items,
            confidence_label=e.confidence_label,
            coverage=e.as_dict()["coverage"],
            baseline_mastery=e.baseline_mastery,
        )

    def as_dict(self) -> dict[str, Any]:
        def r(v: float | None) -> float | None:
            return None if v is None else round(v, 3)

        return {
            "cefr": self.cefr,
            "status": self.status,
            "mastery": r(self.mastery),
            "mastery_low": r(self.mastery_low),
            "mastery_high": r(self.mastery_high),
            "uncertainty": round(self.uncertainty, 3),
            "confidence": self.confidence,
            "confidence_label": self.confidence_label,
            "sample_size": self.sample_size,
            "independent_count": self.independent_count,
            "distinct_items": self.distinct_items,
            "coverage": self.coverage,
            "baseline_mastery": r(self.baseline_mastery),
        }


@dataclass
class CEFRProfile:
    """A learner's multidimensional CEFR profile for one language."""

    language: str
    overall: str | None
    skills: dict[str, SkillAssessment] = field(default_factory=dict)
    overall_status: str = EvidenceStatus.INSUFFICIENT.value
    #: Skills the overall band was computed from.
    overall_basis: list[str] = field(default_factory=list)
    #: Canonical skills with no usable evidence (not assumed weak).
    unassessed_skills: list[str] = field(default_factory=list)
    method: str = METHOD

    def as_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "overall": self.overall,
            "overall_status": self.overall_status,
            "overall_basis": self.overall_basis,
            "unassessed_skills": self.unassessed_skills,
            "method": self.method,
            "skills": {s: a.as_dict() for s, a in self.skills.items()},
        }


def profile_from_estimates(language: str, estimates: dict[str, SkillEstimate]) -> CEFRProfile:
    """Build a profile from already-computed estimates (pure)."""
    skills = {skill: SkillAssessment.from_estimate(e) for skill, e in sorted(estimates.items())}
    basis = [s for s, a in skills.items() if a.cefr is not None and status_rank(a.status) >= 1]
    overall: str | None = None
    overall_status = EvidenceStatus.INSUFFICIENT.value
    if len(basis) >= MIN_SKILLS_FOR_OVERALL:
        bands = [band for band in (skills[s].cefr for s in basis) if band is not None]
        overall = _min_level(bands)
        overall_status = min((skills[s].status for s in basis), key=status_rank)
    unassessed = sorted(
        (set(SKILLS) | set(skills)) - {s for s, a in skills.items() if a.cefr is not None}
    )
    return CEFRProfile(
        language=language,
        overall=overall,
        skills=skills,
        overall_status=overall_status,
        overall_basis=basis if overall is not None else [],
        unassessed_skills=unassessed,
    )


def build_cefr_profile(user_id: str, language: str) -> CEFRProfile:
    """Build a per-skill CEFR profile from the learner's evidence.

    Every skill with any evidence appears (possibly ``insufficient_evidence``
    with ``cefr=None``); skills with none appear only in ``unassessed_skills``.
    """
    estimates = get_knowledge_model().current_estimates(user_id, language)
    return profile_from_estimates(language, estimates)


def persist_profile(user_id: str, profile: CEFRProfile) -> int:
    """Persist a CEFR profile to the assessments store.

    Writes one row per skill (``cefr`` may be ``NULL``, with its ``status``)
    plus one overall row (``skill=NULL``). Returns the number of rows written.
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
            status=a.status,
        )
        written += 1

    basis = [profile.skills[s] for s in profile.overall_basis]
    overall_conf = min((a.confidence for a in basis), default=0.0)
    overall_n = sum(a.sample_size for a in profile.skills.values())
    assessments.record_assessment(
        user_id,
        profile.language,
        skill=None,
        cefr=profile.overall,
        confidence=overall_conf,
        sample_size=overall_n,
        method=METHOD,
        status=profile.overall_status,
    )
    written += 1
    return written
