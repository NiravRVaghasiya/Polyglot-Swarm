"""The evaluation measures the models the app runs by default."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from evals.real import providers as prov
from src.config import Settings, default_model_ids, settings

EVALS_REAL = Path(__file__).parents[2] / "evals" / "real"
# Model-family prefixes; any of these in eval code or configs is a hardcoded id.
_MODEL_ID = re.compile(
    r"\b(claude-|gemini-|gpt-|o\d-|llama\d|gemma\d|granite\d|qwen|mistral)", re.IGNORECASE
)


@pytest.mark.parametrize(
    ("provider", "field"),
    [("claude", "llm_primary"), ("gemini", "llm_fast"), ("openai", "llm_openai")],
)
def test_eval_defaults_equal_the_app_defaults(provider, field):
    app_default = Settings.model_fields[field].default
    assert prov.default_model(provider) == app_default
    assert default_model_ids()[provider] == app_default
    spec = prov.parse_spec(provider)
    assert (spec.model, spec.model_source) == (app_default, prov.APP_DEFAULT)


def test_ollama_default_strips_the_routing_prefix():
    assert default_model_ids()["ollama"].startswith("ollama/")
    assert prov.default_model("ollama") == default_model_ids()["ollama"].removeprefix("ollama/")


def test_environment_does_not_change_the_evaluated_default(monkeypatch):
    monkeypatch.setattr(settings, "llm_primary", "some-local-override")
    monkeypatch.setenv("LLM_PRIMARY", "some-local-override")
    assert prov.default_model("claude") == Settings.model_fields["llm_primary"].default


def test_explicit_override_is_recorded_in_the_probe_record():
    spec = prov.parse_spec("claude:my-pinned-model")
    assert (spec.model, spec.model_source) == ("my-pinned-model", prov.OVERRIDE)
    record = prov.ProbeResult(spec, prov.NOT_CONFIGURED).as_dict()
    assert record["model"] == "my-pinned-model"
    assert record["model_source"] == prov.OVERRIDE
    assert record["app_default_model"] == Settings.model_fields["llm_primary"].default


def test_no_model_id_is_hardcoded_in_eval_code_or_configs():
    # Archived run artifacts (runs/, history.jsonl) and dataset provenance
    # (who wrote the cases) legitimately name models; code and configs must not.
    files = [*EVALS_REAL.glob("*.py"), *EVALS_REAL.glob("configs/*.json")]
    assert files
    offenders = [
        f"{f.name}:{n}: {line.strip()}"
        for f in files
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if _MODEL_ID.search(line)
    ]
    assert not offenders, offenders
