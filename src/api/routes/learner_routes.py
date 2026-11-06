"""Learner-model routes: today's plan, CEFR profile, skill map, insights.

These expose the learner model the rest of the app has been building — the
curriculum planner (Phase 7), the multidimensional CEFR profile (Phase 12), and
the per-skill knowledge model (Phase 6) — over the API so the frontend can
answer "what should I practise today, and why?" (Phase 16).

Since ADR-0031 the CEFR fields are nullable with an explicit evidence status,
and two audit endpoints expose how an estimate was reached: ``/explain/{skill}``
(per-event contributions) and ``/history`` (every recorded mastery update).

Every endpoint is a thin, auth-scoped wrapper over a pure (no-LLM) function, so
they are cheap and safe to serve synchronously like the progress routes.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_current_user
from src.api.schemas import (
    CEFRProfileResponse,
    InsightsResponse,
    LearnerHistoryResponse,
    PlanResponse,
    SkillExplanationResponse,
    SkillMapResponse,
)

router = APIRouter(prefix="/api/v1/learner", tags=["learner"])

# The single default language the app falls back to when none is supplied.
_DEFAULT_LANGUAGE = "Spanish"


@router.get("/plan", response_model=PlanResponse)
def plan(
    language: str = _DEFAULT_LANGUAGE,
    minutes: float = 15.0,
    goal: str = "conversational",
    user_id: str = Depends(get_current_user),
) -> PlanResponse:
    """Return today's ranked next-best learning actions with explanations."""
    from src.curriculum import PlanConstraints, plan_next_actions

    constraints = PlanConstraints(time_available_minutes=minutes, goal=goal)
    actions = plan_next_actions(user_id, language, constraints=constraints)
    return PlanResponse(
        language=language,
        goal=goal,
        actions=[a.as_dict() for a in actions],  # type: ignore[misc]
    )


@router.get("/cefr", response_model=CEFRProfileResponse)
def cefr_profile(
    language: str = _DEFAULT_LANGUAGE,
    user_id: str = Depends(get_current_user),
) -> CEFRProfileResponse:
    """Return the multidimensional CEFR profile: per-skill band + evidence state.

    ``overall`` (and any skill's ``cefr``) is ``null`` until the evidence
    supports a level.
    """
    from src.assessment import build_cefr_profile

    profile = build_cefr_profile(user_id, language)
    return CEFRProfileResponse.model_validate(profile.as_dict())


@router.get("/skill-map", response_model=SkillMapResponse)
def skill_map(
    language: str = _DEFAULT_LANGUAGE,
    user_id: str = Depends(get_current_user),
) -> SkillMapResponse:
    """Return the per-skill estimates (mastery, uncertainty, evidence, coverage)."""
    from src.learner import get_knowledge_model
    from src.learner.estimation import METHOD

    estimates = get_knowledge_model().current_estimates(user_id, language)
    skills = []
    for s, e in sorted(estimates.items()):
        d = e.as_dict()
        skills.append(
            {
                "skill": s,
                "mastery": d["mastery"],
                "uncertainty": d["uncertainty"],
                "sample_size": e.graded_count,
                "status": e.status,
                "mastery_low": d["mastery_low"],
                "mastery_high": d["mastery_high"],
                "independent_count": e.independent_count,
                "effective_n": d["evidence"]["effective_n"],
                "evidence_index": d["evidence_index"],
                "evidence_quality": d["quality"]["score"],
                "coverage": d["coverage"],
                "last_evidence_at": e.last_evidence_at,
            }
        )
    return SkillMapResponse(language=language, method=METHOD, skills=skills)  # type: ignore[arg-type]


@router.get("/explain/{skill}", response_model=SkillExplanationResponse)
def explain_skill(
    skill: str,
    language: str = _DEFAULT_LANGUAGE,
    user_id: str = Depends(get_current_user),
) -> SkillExplanationResponse:
    """Return one skill's estimate and how every evidence event contributed."""
    from src.learner import get_knowledge_model

    estimate = get_knowledge_model().explain(user_id, language, skill)
    if estimate is None:
        raise HTTPException(status_code=404, detail=f"no evidence for skill '{skill}'")
    return SkillExplanationResponse(
        language=language,
        skill=skill,
        estimate=estimate.as_dict(),
        contributions=[asdict(c) for c in estimate.contributions],  # type: ignore[misc]
    )


@router.get("/history", response_model=LearnerHistoryResponse)
def learner_history(
    language: str = _DEFAULT_LANGUAGE,
    skill: str | None = None,
    user_id: str = Depends(get_current_user),
) -> LearnerHistoryResponse:
    """Return the recorded mastery updates (each tied to its evidence), oldest first."""
    from src.learner import get_knowledge_model

    updates = get_knowledge_model().history(user_id, language, skill=skill)
    return LearnerHistoryResponse(language=language, updates=updates)  # type: ignore[arg-type]


@router.get("/cefr-history")
def cefr_history(
    language: str | None = None,
    user_id: str = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    """Return the working-level-over-time series (from session estimates)."""
    from src.memory import progress

    return {"progression": progress.cefr_progression(user_id, language)}


@router.get("/insights", response_model=InsightsResponse)
def insights(
    language: str = _DEFAULT_LANGUAGE,
    user_id: str = Depends(get_current_user),
) -> InsightsResponse:
    """Compose a learner-facing insights summary: where to focus and why.

    Combines the progress overview, the CEFR profile, and the plan's top
    recommendations into one explainable payload. A skill is only called weak
    when its evidence is provisional or better; skills without enough evidence
    are listed under ``needs_assessment`` instead.
    """
    from src.assessment import build_cefr_profile
    from src.curriculum import PlanConstraints, plan_next_actions
    from src.learner.estimation import status_rank
    from src.memory import progress

    overview = progress.progress_overview(user_id, language)
    profile = build_cefr_profile(user_id, language)
    actions = plan_next_actions(user_id, language, constraints=PlanConstraints())

    assessed = [
        a for a in profile.skills.values() if a.mastery is not None and status_rank(a.status) >= 1
    ]
    weakest = sorted(assessed, key=lambda a: (a.mastery or 0.0, a.skill))[:3]

    return InsightsResponse(
        language=language,
        current_cefr=overview.get("current_cefr"),
        overall_cefr=profile.overall,
        overall_status=profile.overall_status,
        weakest_skills=[a.skill for a in weakest],
        needs_assessment=profile.unassessed_skills,
        top_weaknesses=overview.get("top_weaknesses", []),
        recommended_focus=[a.reason for a in actions[:3]],
        streak=overview.get("current_streak", 0),
    )
