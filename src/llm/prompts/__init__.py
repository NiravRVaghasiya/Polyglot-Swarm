"""Jinja2 system-prompt templates for the agents.

Templates live as ``.jinja2`` files in this package directory. :func:`render`
loads and renders one by name, so prompt text lives in version-controlled files
rather than inline string literals scattered across agents.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        undefined=StrictUndefined,  # fail loudly on missing template variables
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # prompts are plain text, not HTML
    )


def render(template_name: str, **context: Any) -> str:
    """Render a prompt template by file name (e.g. ``"cultural.jinja2"``)."""
    template = _environment().get_template(template_name)
    return template.render(**context)
