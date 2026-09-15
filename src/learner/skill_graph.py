"""Skill graph — the prerequisite structure over skills and constructions.

Skills and grammar constructions are not independent: the subjunctive builds on
ser/estar; the genitive builds on the nominative. The skill graph captures those
prerequisite relations so the mastery engine and (later) the curriculum planner
can reason about readiness — e.g. don't push an advanced construction whose
prerequisites are still weak.

Construction prerequisites are sourced from the language packs (Phase 4); the
coarse skill-level graph is a small fixed structure here.
"""

from __future__ import annotations

from src.languages import list_constructions

# Coarse dependencies among the top-level skills. A skill depends on the skills
# that typically underpin it. Deliberately conservative.
_SKILL_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "speaking": ("vocabulary", "grammar"),
    "writing": ("vocabulary", "grammar", "spelling"),
    "reading": ("vocabulary",),
    "listening": ("vocabulary",),
    "pragmatics": ("vocabulary", "grammar"),
    "grammar": (),
    "vocabulary": (),
}


def skill_prerequisites(skill: str) -> tuple[str, ...]:
    """Return the skills that ``skill`` typically depends on."""
    return _SKILL_PREREQUISITES.get(skill, ())


def construction_prerequisites(language: str, construction: str) -> list[str]:
    """Return prerequisite constructions for a construction, from the language pack."""
    for item in list_constructions(language):
        if item.construction == construction:
            return list(item.prerequisites)
    return []


def is_ready(
    skill: str,
    mastery_by_skill: dict[str, float],
    *,
    threshold: float = 0.4,
) -> bool:
    """Whether a learner is "ready" for ``skill``: its prerequisites are >= threshold.

    A skill with no prerequisites is always ready. Missing prerequisite scores
    are treated as 0 (not yet demonstrated).
    """
    for prereq in skill_prerequisites(skill):
        if mastery_by_skill.get(prereq, 0.0) < threshold:
            return False
    return True


def unmet_prerequisites(
    skill: str,
    mastery_by_skill: dict[str, float],
    *,
    threshold: float = 0.4,
) -> list[str]:
    """Return the prerequisite skills that are below ``threshold``."""
    return [p for p in skill_prerequisites(skill) if mastery_by_skill.get(p, 0.0) < threshold]
