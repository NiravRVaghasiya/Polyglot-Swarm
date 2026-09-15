"""Phase 1 tests: structured output, streaming, token counting, task-tier
routing, telemetry, and the OpenAI provider."""

from __future__ import annotations

from src.llm import telemetry
from src.llm.factory import TIER_PREFERENCE, RoutingProvider, get_provider
from src.llm.openai import OpenAIProvider
from src.llm.provider import LLMProvider, Message
from src.llm.router import CAPABILITY_TIERS, TASK_TIER_MAP, is_known_tier, resolve_tier
from src.llm.schemas import (
    GrammarAnalysis,
    VerifierDecision,
    VocabularyExtraction,
    parse_structured,
    strip_code_fences,
)


class StubProvider(LLMProvider):
    def __init__(self, name="stub", reply="hi", *, model=None):
        self.name = name
        self.reply = reply
        self.model = model

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


class TestTaskTierRouting:
    def test_task_tiers_map_to_capability_tiers(self):
        assert resolve_tier("critical_reasoning") == "primary"
        assert resolve_tier("fast_extraction") == "fast"
        assert resolve_tier("cheap_classification") == "fast"
        assert resolve_tier("local_private") == "local"

    def test_capability_tiers_pass_through(self):
        for t in CAPABILITY_TIERS:
            assert resolve_tier(t) == t

    def test_unknown_tier_defaults_to_primary(self):
        assert resolve_tier("nonsense") == "primary"

    def test_is_known_tier(self):
        assert is_known_tier("primary")
        assert is_known_tier("critical_reasoning")
        assert not is_known_tier("nope")

    def test_get_provider_builds_chain_for_task_tier(self, real_providers):
        provider = get_provider("critical_reasoning")
        # Resolves to primary -> claude preferred.
        assert provider.chain[0].name == TIER_PREFERENCE["primary"]

    def test_all_task_tiers_resolve_to_capabilities(self):
        assert set(TASK_TIER_MAP.values()) <= CAPABILITY_TIERS


class TestStructuredOutput:
    def test_strip_code_fences(self):
        assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
        assert strip_code_fences('{"a": 1}') == '{"a": 1}'

    def test_parse_valid(self):
        model = parse_structured('{"errors": [{"original": "x", "rule": "r"}]}', GrammarAnalysis)
        assert model is not None
        assert model.errors[0].rule == "r"

    def test_parse_invalid_json_returns_none(self):
        assert parse_structured("not json", GrammarAnalysis) is None

    def test_parse_schema_mismatch_returns_none(self):
        # words must be a list; give it a string.
        assert parse_structured('{"words": "nope"}', VocabularyExtraction) is None

    def test_verifier_decision_defaults_and_abstain(self):
        d = parse_structured('{"decision": "abstain", "confidence": 0.4}', VerifierDecision)
        assert d is not None
        assert d.decision == "abstain"
        assert d.confidence == 0.4

    async def test_generate_structured_over_chain(self):
        # Fake provider returns {"ok","echo","digest"} which is a valid (empty)
        # GrammarAnalysis after validation.
        router = RoutingProvider([StubProvider(reply='{"errors": []}')], tier="fast")
        model = await router.generate_structured([Message("user", "x")], GrammarAnalysis)
        assert model is not None
        assert model.errors == []


class TestStreamingAndTokens:
    async def test_stream_default_yields_full_text(self):
        provider = StubProvider(reply="hello world")
        chunks = [c async for c in provider.stream([Message("user", "x")])]
        assert "".join(chunks) == "hello world"

    async def test_routing_stream_uses_first_available(self):
        router = RoutingProvider([StubProvider(reply="abc")], tier="fast")
        chunks = [c async for c in router.stream([Message("user", "x")])]
        assert "".join(chunks) == "abc"

    def test_count_tokens_heuristic(self):
        provider = StubProvider()
        n = provider.count_tokens([Message("user", "a" * 40)])
        assert n == 10  # 40 chars // 4


class TestTelemetry:
    def setup_method(self):
        telemetry.reset()
        telemetry.clear_sinks()

    async def test_generate_records_a_run(self):
        router = RoutingProvider([StubProvider(name="s", reply="hello", model="m")], tier="fast")
        await router.generate([Message("user", "hi there")])
        runs = telemetry.recent()
        assert runs
        assert runs[-1].provider == "s"
        assert runs[-1].tier == "fast"
        assert runs[-1].success is True

    async def test_failover_records_failure_then_success(self):
        class Boom(StubProvider):
            async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
                raise RuntimeError("down")

        router = RoutingProvider(
            [Boom(name="bad"), StubProvider(name="good", reply="ok")], tier="primary"
        )
        result = await router.generate([Message("user", "x")])
        assert result == "ok"
        runs = telemetry.recent()
        assert [r.success for r in runs[-2:]] == [False, True]

    def test_sink_receives_runs(self):
        captured = []
        telemetry.register_sink(captured.append)
        telemetry.record(telemetry.ModelRun(provider="p", tier="fast", output_tokens=10))
        assert len(captured) == 1
        assert captured[0].total_tokens == 10

    def test_estimate_cost_free_for_local(self):
        assert telemetry.estimate_cost(None, 1000, 1000) == 0.0
        assert telemetry.estimate_cost("llama3.1:8b", 1000, 1000) == 0.0

    def test_estimate_cost_priced_model(self):
        cost = telemetry.estimate_cost("gpt-4o-mini", 1000, 1000)
        assert cost > 0.0

    async def test_run_stamped_with_interaction_id_in_scope(self):
        # Phase 17: RoutingProvider._record must pick up the ambient
        # interaction id from the observability contextvar.
        from src.observability.context import interaction_scope

        router = RoutingProvider([StubProvider(name="s", reply="hi")], tier="fast")
        with interaction_scope(session_id="sess-1", interaction_id="iid-42"):
            await router.generate([Message("user", "hi")])
        assert telemetry.recent()[-1].interaction_id == "iid-42"

    async def test_run_has_no_interaction_id_outside_scope(self):
        router = RoutingProvider([StubProvider(name="s", reply="hi")], tier="fast")
        await router.generate([Message("user", "hi")])
        assert telemetry.recent()[-1].interaction_id is None


class TestOpenAIProvider:
    def test_unavailable_without_key(self, monkeypatch):
        p = OpenAIProvider(api_key="")
        assert p.is_available() is False

    def test_available_with_key(self):
        p = OpenAIProvider(api_key="sk-test")
        assert p.is_available() is True
        assert p.name == "openai"

    def test_joins_chain_when_key_configured(self, real_providers, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
        chain_names = [p.name for p in get_provider("primary").chain]
        assert "openai" in chain_names

    def test_absent_from_chain_without_key(self, real_providers, monkeypatch):
        from src.config import settings

        monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
        chain_names = [p.name for p in get_provider("primary").chain]
        assert "openai" not in chain_names
        assert set(chain_names) == {"claude", "gemini", "ollama"}
