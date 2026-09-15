"""Versioned prompt templates for the agents.

Templates live as ``.jinja2`` files in this package. Every prompt is
registered in :mod:`src.llm.prompts.registry` with a logical name and a
current version, so which prompt version produced a given output is always
knowable and reproducible (Gate B: versioned prompts).

Two entry points:

- :func:`render_prompt` (preferred) — resolves a registered prompt *name* to a
  :class:`~src.llm.prompts.registry.RenderedPrompt` carrying its name/version.
- :func:`render` (back-compat) — renders a template by raw *file name*, kept so
  existing callers that pass ``"cultural.jinja2"`` keep working; it just
  returns the text.
"""

from __future__ import annotations

from typing import Any

from src.llm.prompts.registry import (
    PROMPT_REGISTRY,
    PromptSpec,
    RenderedPrompt,
    UnknownPromptError,
    prompt_version,
    render_prompt,
)
from src.llm.prompts.registry import _environment as _environment

__all__ = [
    "PROMPT_REGISTRY",
    "PromptSpec",
    "RenderedPrompt",
    "UnknownPromptError",
    "prompt_version",
    "render",
    "render_prompt",
]


def render(template_name: str, **context: Any) -> str:
    """Render a prompt template by raw file name (e.g. ``"cultural.jinja2"``).

    Back-compat shim over the shared jinja2 environment. Prefer
    :func:`render_prompt` (by registered name), which also returns the version.
    """
    template = _environment().get_template(template_name)
    return template.render(**context)
