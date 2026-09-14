"""Scenario schema, loader, and validation.

Scenarios are version-controlled YAML files describing an immersive situation:
a persona, a sequence of objectives (each with target vocabulary), difficulty
scaling per CEFR level, and success criteria. This module parses them into
validated Pydantic models and discovers the shipped scenario library.

Layout: YAML files live under ``src/scenarios/definitions/``. Files may sit in
per-language subdirectories (``definitions/es/restaurant.yaml``) or be named
flatly (``definitions/es_restaurant.yaml``); both are discovered.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

_DEFINITIONS_DIR = Path(__file__).parent / "definitions"


class ScenarioError(Exception):
    """Raised when a scenario file is missing or fails validation."""


class Persona(BaseModel):
    """The character the Conversation Agent plays in a scenario."""

    name: str
    role: str
    personality: str = ""
    dialect: str = ""


class Objective(BaseModel):
    """A single goal the learner should accomplish within the scenario."""

    id: str
    description: str
    required_vocab: list[str] = Field(default_factory=list)


class SuccessCriteria(BaseModel):
    """Thresholds that define completing the scenario successfully."""

    all_objectives_completed: bool = True
    grammar_error_rate_max: float = 0.2
    target_vocabulary_used_min: float = 0.6


class Scenario(BaseModel):
    """A fully validated scenario definition."""

    id: str
    title: str
    language: str
    cefr_min: str = "A1"
    cefr_max: str = "C2"
    location: str = ""
    persona: Persona
    objectives: list[Objective] = Field(default_factory=list)
    difficulty_scaling: dict[str, str] = Field(default_factory=dict)
    opening_line: str = ""
    success_criteria: SuccessCriteria = Field(default_factory=SuccessCriteria)
    cultural_notes: list[str] = Field(default_factory=list)

    def scaling_for(self, cefr_level: str) -> str:
        """Return the difficulty-scaling guidance for a CEFR level, if defined."""
        return self.difficulty_scaling.get(cefr_level, "")


def _parse_scenario_dict(data: object, *, source: str) -> Scenario:
    # Scenario files wrap the definition under a top-level "scenario:" key.
    body = data.get("scenario", data) if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise ScenarioError(f"{source}: expected a mapping under 'scenario:'")
    try:
        return Scenario.model_validate(body)
    except ValidationError as exc:
        raise ScenarioError(f"{source}: invalid scenario — {exc}") from exc


def load_scenario_file(path: str | Path) -> Scenario:
    """Load and validate a single scenario YAML file."""
    p = Path(path)
    if not p.exists():
        raise ScenarioError(f"Scenario file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"{p}: malformed YAML — {exc}") from exc
    return _parse_scenario_dict(raw, source=str(p))


def _iter_scenario_files() -> list[Path]:
    """Return all scenario YAML files under the definitions directory."""
    if not _DEFINITIONS_DIR.exists():
        return []
    return sorted(
        [p for p in _DEFINITIONS_DIR.rglob("*.yaml")]
        + [p for p in _DEFINITIONS_DIR.rglob("*.yml")]
    )


def list_scenarios(language: str | None = None) -> list[Scenario]:
    """Load and validate every shipped scenario, optionally filtered by language."""
    scenarios = [load_scenario_file(p) for p in _iter_scenario_files()]
    if language is not None:
        scenarios = [s for s in scenarios if s.language == language]
    return scenarios


def get_scenario(scenario_id: str) -> Scenario:
    """Load a single scenario by its ``id``.

    Raises :class:`ScenarioError` if no scenario with that id exists.
    """
    for scenario in list_scenarios():
        if scenario.id == scenario_id:
            return scenario
    raise ScenarioError(f"No scenario with id {scenario_id!r}")
