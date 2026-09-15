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

from functools import lru_cache
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
    """A fully validated scenario definition.

    Beyond a persona + objectives, a scenario is a *pedagogical environment*
    (Phase 13): it declares the grammar constructions, vocabulary, and
    communicative functions it is designed to elicit, the constraints the tutor
    should honor, the conditions that count as failure, and the cross-language
    transfer opportunities it creates. These target fields are optional so
    existing scenario YAML keeps parsing.
    """

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

    # --- Phase 13: pedagogical targets (all optional) ---
    #: Grammar construction ids the scenario should create opportunities for.
    target_grammar: list[str] = Field(default_factory=list)
    #: Vocabulary the scenario should work in (beyond per-objective required_vocab).
    target_vocabulary: list[str] = Field(default_factory=list)
    #: Communicative functions to elicit (e.g. "make a polite request").
    target_functions: list[str] = Field(default_factory=list)
    #: Constraints the tutor must honor (e.g. "stay in the restaurant setting").
    constraints: list[str] = Field(default_factory=list)
    #: Conditions that count as failing the scenario (e.g. "switched to English").
    failure_conditions: list[str] = Field(default_factory=list)
    #: Cross-language transfer opportunities this scenario surfaces.
    transfer_opportunities: list[str] = Field(default_factory=list)

    def scaling_for(self, cefr_level: str) -> str:
        """Return the difficulty-scaling guidance for a CEFR level, if defined."""
        return self.difficulty_scaling.get(cefr_level, "")

    def all_target_vocabulary(self) -> list[str]:
        """Union of scenario-level target vocab and every objective's required vocab."""
        words = list(self.target_vocabulary)
        for obj in self.objectives:
            words.extend(obj.required_vocab)
        # De-duplicate preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for w in words:
            key = w.lower()
            if key not in seen:
                seen.add(key)
                out.append(w)
        return out


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
    """Load and validate a single scenario YAML file.

    Validation is two-layered (Phase 20): structural (Pydantic, via
    :func:`_parse_scenario_dict`) and content-level (
    :func:`src.safety.roleplay.validate_scenario_content`) — a scenario is a
    free-text document that gets interpolated into the conversation agent's
    *system* prompt, so a malicious or compromised scenario file is treated
    with the same suspicion as any other content that could smuggle
    instructions into a trusted prompt role.

    Phase 22 caching: scenarios are version-controlled, static data — parsing
    and validating the same YAML on every single turn/session start is pure
    waste. Results are cached by ``(path, mtime)`` (see
    :func:`_load_scenario_file_cached`), so editing a scenario file on disk
    (a normal dev/content workflow) still picks up the change on the next
    load rather than serving a stale cached parse, unlike caching by path
    alone. A missing file is *not* cached (raising skips the cache), so a
    file that appears after a failed lookup is picked up immediately.

    Returned :class:`Scenario` instances are shared across callers (the cache
    hands back the same object) — treat them as read-only; nothing in this
    codebase mutates a loaded ``Scenario`` in place, and callers should not
    start doing so.
    """
    p = Path(path)
    if not p.exists():
        raise ScenarioError(f"Scenario file not found: {p}")
    mtime = p.stat().st_mtime
    return _load_scenario_file_cached(str(p), mtime)


@lru_cache(maxsize=256)
def _load_scenario_file_cached(path_str: str, mtime: float) -> Scenario:
    """The actual parse+validate work, cached by path and modification time.

    ``mtime`` is part of the cache key purely to invalidate automatically when
    a scenario file changes on disk — it is not used for anything else.
    """
    p = Path(path_str)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"{p}: malformed YAML — {exc}") from exc
    scenario = _parse_scenario_dict(raw, source=str(p))

    from src.safety.roleplay import ScenarioContentError, validate_scenario_content

    try:
        validate_scenario_content(scenario)
    except ScenarioContentError as exc:
        raise ScenarioError(f"{p}: {exc}") from exc

    return scenario


def clear_scenario_cache() -> None:
    """Clear the cached scenario parses (tests / hot-reload tooling)."""
    _load_scenario_file_cached.cache_clear()


def _iter_scenario_files() -> list[Path]:
    """Return all scenario YAML files under the definitions directory."""
    if not _DEFINITIONS_DIR.exists():
        return []
    return sorted(
        [p for p in _DEFINITIONS_DIR.rglob("*.yaml")] + [p for p in _DEFINITIONS_DIR.rglob("*.yml")]
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
