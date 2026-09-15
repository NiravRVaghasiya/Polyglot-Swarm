"""Tests for the versioned prompt registry (Gate B: versioned prompts).

Verifies that every agent prompt is registered with a version, resolves to a
real template file, renders with a carried name/version, and that pinning a
version and looking up an unknown name behave correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.llm.prompts import PROMPT_REGISTRY, RenderedPrompt, prompt_version, render_prompt
from src.llm.prompts.registry import UnknownPromptError, _versioned_template_name

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "llm" / "prompts"


class TestRegistryIntegrity:
    def test_every_registered_template_file_exists(self):
        for name, spec in PROMPT_REGISTRY.items():
            path = _PROMPTS_DIR / spec.template
            assert path.exists(), f"prompt {name!r} -> missing template {spec.template}"

    def test_every_prompt_has_a_positive_version(self):
        for spec in PROMPT_REGISTRY.values():
            assert spec.version >= 1

    def test_core_agent_prompts_are_registered(self):
        # The four prompts migrated from inline string constants in Gate B.
        for name in ("conversation", "grammar", "vocabulary", "review"):
            assert name in PROMPT_REGISTRY

    def test_previously_templated_prompts_are_registered(self):
        for name in ("cultural", "evaluator", "drills", "ingestion", "peer", "writing"):
            assert name in PROMPT_REGISTRY


class TestRenderPrompt:
    def test_renders_and_carries_name_and_version(self):
        rendered = render_prompt(
            "grammar",
            language="Spanish",
            cefr_level="A2",
            weaknesses="none",
            user_text="Hola",
        )
        assert isinstance(rendered, RenderedPrompt)
        assert rendered.name == "grammar"
        assert rendered.version == prompt_version("grammar")
        # str() is the prompt text.
        assert "Spanish" in str(rendered)
        assert "Hola" in str(rendered)

    def test_vocabulary_prompt_interpolates(self):
        text = str(
            render_prompt(
                "vocabulary",
                language="Italian",
                cefr_level="B1",
                user_text="Ciao",
                agent_text="Buongiorno",
            )
        )
        assert "Italian" in text
        assert "Ciao" in text
        assert "Buongiorno" in text

    def test_defaults_to_current_version(self):
        rendered = render_prompt(
            "review",
            language="Polish",
            word="dom",
            translation="house",
            context="",
            scenario_hint="",
        )
        assert rendered.version == PROMPT_REGISTRY["review"].version

    def test_unknown_prompt_raises(self):
        with pytest.raises(UnknownPromptError):
            render_prompt("no_such_prompt")

    def test_prompt_version_of_unknown_raises(self):
        with pytest.raises(UnknownPromptError):
            prompt_version("no_such_prompt")


class TestVersionResolution:
    def test_current_version_uses_registered_filename(self):
        spec = PROMPT_REGISTRY["grammar"]
        assert _versioned_template_name("grammar", spec.version) == spec.template

    def test_older_version_uses_conventional_filename(self):
        # A hypothetical v2 would resolve to grammar_v2.jinja2 (whether or not
        # that file exists yet) — proving version selection is real.
        assert _versioned_template_name("grammar", 2) == "grammar_v2.jinja2"


class TestBackCompatRender:
    def test_render_by_filename_still_works(self):
        from src.llm.prompts import render

        text = render(
            "cultural.jinja2",
            language="Spanish",
            context="cafe",
            persona_role="waiter",
            location="Madrid",
            cefr_level="A2",
            user_text="Hola",
        )
        assert "Spanish" in text
