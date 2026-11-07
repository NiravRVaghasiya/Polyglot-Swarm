"""The real-model runner, offline: a scripted provider stands in for the model.

Checks the guarantees that matter for trustworthy results — production-identical
prompts, raw-response capture, timeouts/retries, unavailable vs failed
providers, no silent synthetic substitution, resumability, run status — plus
report generation and regression detection on the resulting artifacts.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from evals.real import providers as prov
from evals.real import regression, report, runner
from evals.real.config import EvalConfig
from src.llm.provider import Completion, LLMProvider, Message


class Scripted(LLMProvider):
    """Answers grammar prompts by keyword; can be made slow, failing or flaky."""

    name = "scripted"

    def __init__(self, *, behavior="good", fail_first=0, delay=0.0, available=True):
        self.behavior = behavior
        self.fail_first = fail_first
        self.delay = delay
        self.available = available
        self.calls: list[list[Message]] = []

    def is_available(self) -> bool:
        return self.available

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return (await self.generate_detailed(messages)).text

    async def generate_detailed(
        self, messages, *, temperature=0.7, max_tokens=512, json_mode=False
    ):
        self.calls.append(messages)
        if self.behavior == "auth":
            raise RuntimeError("Error code: 401 - invalid x-api-key (authentication_error)")
        is_probe = "Reply with the single word OK" in messages[-1].content
        if self.fail_first > 0 and not is_probe:
            self.fail_first -= 1
            await asyncio.sleep(10)  # longer than the test timeout
        if self.delay and not is_probe:
            await asyncio.sleep(self.delay)
        text = messages[-1].content
        if "Reply with the single word OK" in text:
            body = "OK"
        elif "soy hambre" in text and self.behavior in ("good", "bare"):
            errors = [
                {
                    "original": "soy hambre",
                    "correction": "tengo hambre",
                    "construction": "ser_vs_tener",
                    "rule": "ser_vs_tener",
                    "explanation": "",
                    "classification": "wrong",
                    "severity": "critical",
                    "confidence": 0.9,
                    "alternatives": [],
                }
            ]
            # "bare" answers with a top-level list, which production reads as no errors.
            body = json.dumps(errors if self.behavior == "bare" else {"errors": errors})
        elif "vocabulary" in messages[0].content.lower() or '"words"' in text:
            body = '{"words": []}'
        else:
            body = '{"errors": []}'
        return Completion(body, 100, 10, False, "scripted-1")


@pytest.fixture
def scripted(monkeypatch):
    made: dict[str, Scripted] = {}

    def build(spec, *, allow_synthetic=False):
        if spec.synthetic and not allow_synthetic:
            raise prov.SyntheticProviderError("synthetic")
        return made.setdefault(spec.model, Scripted(**SCRIPTS.get(spec.model, {})))

    monkeypatch.setattr(prov, "build_provider", build)
    return made


SCRIPTS: dict[str, dict] = {
    "good": {},
    "bad": {"behavior": "bad"},
    "bare": {"behavior": "bare"},
    "auth": {"behavior": "auth"},
    "absent": {"available": False},
    "flaky": {"fail_first": 1},
}


def _config(**kw):
    return EvalConfig(tasks=["grammar"], timeout_s=0.5, max_retries=1, retry_backoff_s=0.0, **kw)


def _run(tmp_path, specs, run_id, config=None, **kw):
    return asyncio.run(
        runner.run(config or _config(), specs, run_id=run_id, runs_dir=tmp_path, **kw)
    )


def _records(run_dir):
    return [
        json.loads(line) for line in (run_dir / "responses.jsonl").read_text("utf-8").splitlines()
    ]


class TestPlanning:
    def test_messages_are_identical_to_production(self):
        from src.agents.grammar import build_grammar_messages

        calls, datasets = runner.plan_calls(_config())
        first = calls[0]
        assert datasets["grammar"]["split"] == "test"
        assert first.temperature == 0.0 and first.max_tokens == 700  # production parameters
        from evals.real.datasets import load_split

        _, cases = load_split("grammar", "test")
        case = next(c for c in cases if c.case_id == first.case_id)
        expected = build_grammar_messages(
            case.language, cefr_level=case.cefr_level, weaknesses=[], user_text=case.text
        )
        assert first.messages == expected

    def test_context_variant_only_where_context_exists(self):
        calls, _ = runner.plan_calls(_config(grammar_prompts=["grammar@1", "grammar_context@1"]))
        variant = [c for c in calls if c.prompt == "grammar_context@1"]
        assert variant and all("Situation:" in c.messages[-1].content for c in variant)
        assert all("not specified" not in c.messages[-1].content for c in variant)


class TestRunner:
    def test_complete_run_records_everything(self, tmp_path, scripted):
        run_dir = _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "r1", limit=3)
        manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
        assert manifest["status"] == "complete"
        assert manifest["synthetic"] is False
        assert manifest["datasets"]["grammar"]["sha256"]
        assert manifest["prompts"]["grammar@1"]["sha256"]
        assert manifest["git"]["commit"]
        recs = _records(run_dir)
        assert len(recs) == 3
        r = recs[0]
        assert r["messages"] and r["response_text"] and r["reported_model"] == "scripted-1"
        assert r["input_tokens"] == 100 and r["tokens_estimated"] is False

    def test_unavailable_providers_are_not_substituted(self, tmp_path, scripted):
        specs = [
            prov.ProviderSpec("ollama", "good"),
            prov.ProviderSpec("claude", "auth"),
            prov.ProviderSpec("openai", "absent"),
        ]
        run_dir = _run(tmp_path, specs, "r2", limit=2)
        manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
        statuses = {p["model"]: p["status"] for p in manifest["providers"]}
        assert statuses == {"good": "available", "auth": "auth_failed", "absent": "not_configured"}
        assert {r["model"] for r in _records(run_dir)} == {"good"}
        assert manifest["status"] == "partial"  # requested providers are missing
        rep = report.build_report(run_dir)
        states = {p["provider"]: p["state"] for p in rep["completeness"]["providers"]}
        assert states["claude:auth"] == "unavailable (auth_failed)"

    def test_timeout_then_retry_succeeds(self, tmp_path, scripted):
        run_dir = _run(tmp_path, [prov.ProviderSpec("ollama", "flaky")], "r3", limit=1)
        r = _records(run_dir)[0]
        assert r["ok"] and r["attempts"] == 2 and r["errors"][0].startswith("timeout")

    def test_exhausted_retries_are_failures_not_results(self, tmp_path, scripted):
        scripted["slow"] = Scripted(delay=5)
        run_dir = _run(tmp_path, [prov.ProviderSpec("ollama", "slow")], "r4", limit=1)
        r = _records(run_dir)[0]
        assert not r["ok"] and r["error_category"] == "timeout" and r["response_text"] is None
        manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
        assert manifest["status"] == "failed"

    def test_synthetic_requires_opt_in_and_is_labeled(self, tmp_path):
        with pytest.raises(prov.SyntheticProviderError):
            prov.build_provider(prov.parse_spec("fake"))
        result = asyncio.run(prov.probe(prov.parse_spec("fake")))
        assert result.status == "error"
        run_dir = _run(tmp_path, [prov.parse_spec("fake")], "r5", limit=1, allow_synthetic=True)
        manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
        assert manifest["synthetic"] is True
        assert "YES" in report.render_markdown(report.build_report(run_dir))

    def test_resume_skips_completed_calls(self, tmp_path, scripted):
        _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "r6", limit=2)
        before = len(scripted["good"].calls)
        _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "r6", limit=3)
        # One probe call plus only the one new case.
        assert len(scripted["good"].calls) - before == 2
        assert len(_records(tmp_path / "r6")) == 3


class TestReportsAndRegression:
    def test_report_and_gates(self, tmp_path, scripted, monkeypatch):
        monkeypatch.setattr(regression, "HISTORY_PATH", tmp_path / "history.jsonl")
        run_dir = _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "r7")
        out = report.write_report(run_dir, record_history=False)
        data = json.loads((out / "report.json").read_text("utf-8"))
        g = data["providers"]["ollama:good"]["grammar"]
        assert g["cases_labeled"] > 0 and g["recall"]["denominator"] > 0
        assert data["gates"]["production_gate"] == "not_established"
        assert "provisional" in (out / "report.md").read_text("utf-8")
        assert regression.record_history(data, tmp_path / "history.jsonl") == 1
        regression.record_history(data, tmp_path / "history.jsonl")  # replaces, no duplicate
        assert len((tmp_path / "history.jsonl").read_text("utf-8").splitlines()) == 1

    def test_bare_list_sensitivity_is_diagnostic_only(self, tmp_path, scripted):
        specs = [prov.ProviderSpec("ollama", "good"), prov.ProviderSpec("ollama", "bare")]
        data = report.build_report(_run(tmp_path, specs, "r9"))
        good, bare = data["providers"]["ollama:good"], data["providers"]["ollama:bare"]
        assert good["bare_list_sensitivity"] is None
        assert bare["structured"]["bare_list_rate"]["numerator"] > 0
        # As shipped, the bare-list answers count as "no errors" ...
        assert bare["grammar"]["confusion"]["tp"] == 0
        # ... and the diagnostic shows what the model actually said, matching
        # the well-formed provider, without touching the gated metrics.
        sens = bare["bare_list_sensitivity"]["grammar"]
        assert sens["confusion"] == good["grammar"]["confusion"]
        recall_gate = next(
            g
            for g in data["gates"]["results"]
            if g["provider"] == "ollama:bare" and g["metric"] == "grammar.recall"
        )
        assert recall_gate["value"] == bare["grammar"]["recall"]["value"]

    def test_regression_detected_with_paired_test(self, tmp_path, scripted):
        base = _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "base")
        # Same provider key, but the candidate never finds errors.
        scripted["good"] = Scripted(behavior="bad")
        cand = _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "cand")
        result = regression.compare_runs(base, cand)
        assert result["comparable"]
        comp = result["comparisons"][0]
        # The scripted "good" model only catches 'soy hambre' cases, so the
        # difference is a handful of cases: the test must not over-claim.
        assert comp["base_only_correct"] >= 1
        assert comp["decision"] in ("regression", "no_significant_change")
        if comp["base_only_correct"] < 6:
            assert comp["decision"] == "no_significant_change"

    def test_synthetic_and_real_runs_are_incomparable(self, tmp_path, scripted):
        real = _run(tmp_path, [prov.ProviderSpec("ollama", "good")], "real", limit=2)
        synth = _run(tmp_path, [prov.parse_spec("fake")], "synth", limit=2, allow_synthetic=True)
        result = regression.compare_runs(real, synth)
        assert not result["comparable"]
        assert "synthetic" in result["reasons"][0]


class TestErrorClassification:
    @pytest.mark.parametrize(
        ("exc", "category"),
        [
            (RuntimeError("Error code: 401 - invalid x-api-key"), "auth_failed"),
            (RuntimeError("API key not valid. Please pass a valid API key."), "auth_failed"),
            (RuntimeError("model 'x' not found, try pulling it first"), "model_not_found"),
            (ConnectionError("Failed to connect to localhost:11434"), "unreachable"),
            (TimeoutError(), "timeout"),
            (ImportError("no module"), "sdk_missing"),
            (RuntimeError("CUDA error"), "error"),
        ],
    )
    def test_classify(self, exc, category):
        assert prov.classify_error(exc) == category
