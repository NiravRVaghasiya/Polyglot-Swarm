"""Sensitive-role-play guardrails and scenario content validation.

Two policies:

1. **Sensitive personas** (doctor, lawyer, pharmacist, ...) are legitimate and
   valuable scenarios for language learning (Phase 13 ships a doctor scenario
   in every language pack), but the persona must never be allowed to drift
   into actually giving medical or legal advice — the point is vocabulary and
   register practice, not diagnosis or legal counsel. :func:`disclaimer_for_role`
   returns an instruction to append to the conversation system prompt for
   these roles.
2. **Scenario content validation** (:func:`validate_scenario_content`) — the
   plan calls out "malicious scenario definitions" as a distinct risk from
   ordinary user chat: a scenario ships as free-text YAML (persona
   personality, objectives, constraints, ...) that gets interpolated into the
   *system*-role conversation prompt. :mod:`src.scenarios.loader` already
   validates structure (Pydantic) and uses ``yaml.safe_load``; this adds a
   content-level check so a scenario containing an injection attempt is
   rejected at load time, before it ever reaches an agent prompt.
"""

from __future__ import annotations

from src.safety.injection import scan_for_injection

#: Role-name substrings that indicate a sensitive persona needing the
#: disclaimer. Matched case-insensitively against the persona's ``role``
#: field. Deliberately a role-based check (not a content-based one): a
#: waiter or shopkeeper persona never needs this, regardless of what they say.
SENSITIVE_ROLE_KEYWORDS: frozenset[str] = frozenset(
    {
        "doctor",
        "physician",
        "practitioner",
        "nurse",
        "pharmacist",
        "psychiatrist",
        "psychologist",
        "therapist",
        "lawyer",
        "attorney",
        "solicitor",
        "notary",
        "judge",
    }
)

#: Appended to the conversation system prompt for sensitive personas. Kept
#: short and in-character-compatible: the persona keeps role-playing for
#: language practice, it just never gives real advice.
_SENSITIVE_ROLE_DISCLAIMER = (
    "IMPORTANT: This is a language-learning role-play only. Even while playing "
    "this role, do not give real medical, legal, or other professional advice "
    "the learner might act on outside this exercise — keep any diagnosis, "
    "prescription, or legal counsel generic and clearly part of the practice "
    "scenario, and if the learner asks something a real professional should "
    "answer, gently note that this is practice, not real advice."
)


def is_sensitive_role(role: str) -> bool:
    """Whether a persona's ``role`` string names a sensitive profession."""
    role_lower = (role or "").lower()
    return any(keyword in role_lower for keyword in SENSITIVE_ROLE_KEYWORDS)


def disclaimer_for_role(role: str) -> str:
    """Return the disclaimer text to append for a sensitive role, or ``""``.

    Callers append the (possibly empty) result to the conversation system
    prompt; an empty string is a no-op for non-sensitive personas so ordinary
    scenarios are unaffected.
    """
    return _SENSITIVE_ROLE_DISCLAIMER if is_sensitive_role(role) else ""


#: The scenario text fields checked for injection content. Free-text fields
#: only — structured fields (id, cefr levels, required_vocab word lists) are
#: already tightly typed/short and not natural injection vectors.
_SCENARIO_TEXT_FIELDS = (
    "location",
    "opening_line",
)


class ScenarioContentError(ValueError):
    """Raised when a scenario's content (not structure) fails validation."""


def validate_scenario_content(scenario: object) -> None:
    """Reject a scenario whose free-text fields look like a prompt injection.

    Takes a validated :class:`src.scenarios.loader.Scenario` (typed loosely as
    ``object`` here to avoid a hard import-time dependency from ``src.safety``
    on ``src.scenarios`` — this module is invoked FROM the loader, not the
    other way around). Raises :class:`ScenarioContentError` naming the first
    offending field; callers should treat this the same as the loader's
    existing :class:`~src.scenarios.loader.ScenarioError` for structural
    validation (both mean "do not use this scenario file").
    """
    checks: list[tuple[str, str]] = []
    for field in _SCENARIO_TEXT_FIELDS:
        value = getattr(scenario, field, "") or ""
        checks.append((field, value))

    persona = getattr(scenario, "persona", None)
    if persona is not None:
        for field in ("name", "role", "personality", "dialect"):
            checks.append((f"persona.{field}", getattr(persona, field, "") or ""))

    for i, objective in enumerate(getattr(scenario, "objectives", []) or []):
        checks.append((f"objectives[{i}].description", getattr(objective, "description", "") or ""))

    for field in ("constraints", "failure_conditions", "target_functions", "cultural_notes"):
        for i, item in enumerate(getattr(scenario, field, []) or []):
            checks.append((f"{field}[{i}]", str(item)))

    for field_name, text in checks:
        hits = scan_for_injection(text)
        if hits:
            raise ScenarioContentError(
                f"scenario field {field_name!r} looks like a prompt-injection "
                f"attempt (matched {hits!r}): {text!r}"
            )
