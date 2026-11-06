"""Provenance — where an evidence event came from.

Every learner-state change must be explainable: which component/model produced
the observation, in which interaction, at what time, and under which prompt and
rubric versions. This makes debugging, reproducibility, and rollback possible
(Phase 3, ADR-0031), and feeds the observability story (Phase 17).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provenance:
    """The origin of an evidence event.

    Attributes:
        source: Component/model version that produced the observation, e.g.
            ``"grammar-agent-v1"`` or ``"srs-review"``.
        session_id: The session the observation occurred in.
        interaction_id: A finer-grained id for the specific turn/interaction.
        model_version: Optional underlying LLM/model identifier.
        rubric_version: Version of the grading rubric/taxonomy that judged the
            observation (e.g. ``"grammar-taxonomy-v1"``).
        prompt_version: Version of the prompt that produced the judgment
            (e.g. ``"grammar@1"`` from the versioned prompt registry).
    """

    source: str
    session_id: str | None = None
    interaction_id: str | None = None
    model_version: str | None = None
    rubric_version: str | None = None
    prompt_version: str | None = None
