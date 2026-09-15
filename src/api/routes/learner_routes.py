"""Learner-model routes: today's plan, CEFR profile, skill map, insights.

These expose the learner model the rest of the app has been building — the
curriculum planner (Phase 7), the multidimensional CEFR profile (Phase 12), and
the per-skill knowledge model (Phase 6) — over the API so the frontend can
answer "what should I practise today, and why?" (Phase 16).

Every endpoint is a thin, auth-scoped wrapper over a pure (no-LLM) function, so
they are cheap and safe to serve synchronously like the progress routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.api.schemas import (
    CEFRProfileResponse,
    InsightsResponse,
    PlanResponse,
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
    """Return the multidimensional CEFR profile: per-skill band + confidence."""
    from src.assessment import build_cefr_profile

    profile = build_cefr_profile(user_id, language)
    return CEFRProfileResponse.model_validate(profile.as_dict())


@router.get("/skill-map", response_model=SkillMapResponse)
def skill_map(
    language: str = _DEFAULT_LANGUAGE,
    user_id: str = Depends(get_current_user),
) -> SkillMapResponse:
    """Return the raw per-skill beliefs (mastery + uncertainty + evidence)."""
    from src.learner import get_knowledge_model

    beliefs = get_knowledge_model().current_beliefs(user_id, language)
    skills = [
        {
            "skill": s,
            "mastery": round(b.mastery, 3),
            "uncertainty": round(b.uncertainty, 3),
            "sample_size": int(round(b.sample_size)),
        }
        for s, b in sorted(beliefs.items())
    ]
    return SkillMapResponse(language=language, skills=skills)  # type: ignore[arg-type]


@router.get("/cefr-history")
def cefr_history(
    language: str | None = None,
    user_id: str = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    """Return the CEFR-over-time series (from session estimates)."""
    from src.memory import progress

    return {"progression": progress.cefr_progression(user_id, language)}


@router.get("/insights", response_model=InsightsResponse)
def insights(
    language: str = _DEFAULT_LANGUAGE,
    user_id: str = Depends(get_current_user),
) -> InsightsResponse:
    """Compose a learner-facing insights summary: where to focus and why.

    Combines the progress overview, the CEFR profile, and the plan's top
    recommendations into one explainable payload.
    """
    from src.assessment import build_cefr_profile
    from src.curriculum import PlanConstraints, plan_next_actions
    from src.memory import progress

    overview = progress.progress_overview(user_id, language)
    profile = build_cefr_profile(user_id, language)
    actions = plan_next_actions(user_id, language, constraints=PlanConstraints())

    # Weakest skills = lowest-mastery skills in the profile.
    weakest = sorted(profile.skills.values(), key=lambda a: a.mastery)[:3]
    weakest_skills = [a.skill for a in weakest]

    return InsightsResponse(
        language=language,
        current_cefr=overview.get("current_cefr"),
        overall_cefr=profile.overall,
        weakest_skills=weakest_skills,
        top_weaknesses=overview.get("top_weaknesses", []),
        recommended_focus=[a.reason for a in actions[:3]],
        streak=overview.get("current_streak", 0),
    )
