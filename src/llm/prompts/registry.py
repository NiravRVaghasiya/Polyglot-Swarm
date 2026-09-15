"""Versioned prompt registry (Gate B: versioned prompts).

The agents' prompts were previously a mix of jinja2 templates loaded by name
(no version) and inline Python string constants scattered across agent modules
(no version, not even in the template system). That is not "versioned prompts":
there was no way to tell which prompt version produced a given output, no
single place that pins the current version of each prompt, and no consistency
across agents.

This registry is the single source of truth: every agent prompt has a logical
name, a current version, and a template file. :func:`render_prompt` resolves a
name (optionally pinned to a specific version) to a rendered
:class:`RenderedPrompt` that carries its own ``name`` and ``version`` — so the
version can be recorded in telemetry and reproduced later. Older versions can
coexist (a new ``*_vN.jinja2`` file plus a registry bump), which is what makes
a prompt change auditable and reversible rather than a silent edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class PromptSpec:
    """The registry entry for one logical prompt: its current version + file."""

    name: str
    version: int
    template: str  # the jinja2 filename for the current version


@dataclass(frozen=True)
class RenderedPrompt:
    """A rendered prompt plus the identity of the template that produced it.

    ``str(rendered)`` is the prompt text, so it can be passed straight into a
    ``Message`` without callers caring about the wrapper; the ``name``/
    ``version`` are available for telemetry and reproducibility.
    """

    text: str
    name: str
    version: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.text


#: The prompt manifest: logical name -> current version + template file.
#: Bumping a prompt means adding a new ``<name>_vN.jinja2`` and updating the
#: version/template here in the same change, so the current version of every
#: prompt is always visible in one place and older versions stay on disk.
PROMPT_REGISTRY: dict[str, PromptSpec] = {
    # Core agent prompts (migrated from inline string constants in Gate B).
    "conversation": PromptSpec("conversation", 1, "conversation_v1.jinja2"),
    "grammar": PromptSpec("grammar", 1, "grammar_v1.jinja2"),
    "vocabulary": PromptSpec("vocabulary", 1, "vocabulary_v1.jinja2"),
    "review": PromptSpec("review", 1, "review_v1.jinja2"),
    # Prompts that already lived as jinja2 templates — now registered/versioned
    # too, so every agent prompt goes through one versioned path.
    "cultural": PromptSpec("cultural", 1, "cultural.jinja2"),
    "evaluator": PromptSpec("evaluator", 1, "evaluator.jinja2"),
    "drills": PromptSpec("drills", 1, "drills.jinja2"),
    "ingestion": PromptSpec("ingestion", 1, "ingestion.jinja2"),
    "peer": PromptSpec("peer", 1, "peer.jinja2"),
    "transfer": PromptSpec("transfer", 1, "transfer.jinja2"),
    "transfer_verify": PromptSpec("transfer_verify", 1, "transfer_verify.jinja2"),
    "writing": PromptSpec("writing", 1, "writing.jinja2"),
}


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        undefined=StrictUndefined,  # fail loudly on a missing template variable
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # prompts are plain text, not HTML
        keep_trailing_newline=True,
    )


class UnknownPromptError(KeyError):
    """Raised when a prompt name is not in the registry."""


def _versioned_template_name(name: str, version: int) -> str:
    """The jinja2 filename for a specific version of a named prompt.

    Uses the registry's current template when the requested version matches the
    current one; otherwise derives the conventional ``<name>_vN.jinja2`` name,
    so a pinned older version resolves to its own file if present.
    """
    spec = PROMPT_REGISTRY[name]
    if version == spec.version:
        return spec.template
    return f"{name}_v{version}.jinja2"


def prompt_version(name: str) -> int:
    """Return the current version registered for a prompt name."""
    try:
        return PROMPT_REGISTRY[name].version
    except KeyError as exc:  # noqa: PERF203 - clarity over micro-optimization
        raise UnknownPromptError(name) from exc


def render_prompt(name: str, *, version: int | None = None, **context: Any) -> RenderedPrompt:
    """Render a registered prompt, returning its text plus name/version.

    Args:
        name: The logical prompt name (a key of :data:`PROMPT_REGISTRY`).
        version: A specific version to render; defaults to the registered
            current version.
        **context: Template variables.

    Raises:
        UnknownPromptError: if ``name`` is not registered.
    """
    if name not in PROMPT_REGISTRY:
        raise UnknownPromptError(name)
    resolved_version = version if version is not None else PROMPT_REGISTRY[name].version
    template_name = _versioned_template_name(name, resolved_version)
    template = _environment().get_template(template_name)
    text = template.render(**context)
    return RenderedPrompt(text=text, name=name, version=resolved_version)
