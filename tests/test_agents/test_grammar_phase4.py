"""Phase 4 tests: grammar taxonomy, classification -> assessment, taxonomy
loader, and the precision/false-correction benchmark."""

from __future__ import annotations

from src.agents import grammar
from src.agents.grammar import _select_errors, _to_grammar_error
from src.languages import get_construction, list_constructions, load_taxonomy
from src.llm.provider import LLMProvider
from src.llm.schemas import (
    ERROR_CLASSIFICATIONS,
    GRAMMAR_CLASSIFICATIONS,
    GrammarAnalysis,
    GrammarErrorModel,
    GrammarItem,
)


class _FakeProvider(LLMProvider):
    """A provider returning a canned string; inherits generate_structured."""

    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply

    def is_available(self) -> bool:
        return True

    async def generate(self, messages, *, temperature=0.7, max_tokens=512, json_mode=False):
        return self.reply


def _analysis(**kw) -> GrammarAnalysis:
    return GrammarAnalysis(errors=[GrammarErrorModel(**kw)])


class TestClassificationModel:
    def test_wrong_and_awkward_are_errors(self):
        assert GrammarErrorModel(original="x", classification="wrong").is_error()
        assert GrammarErrorModel(original="x", classification="awkward").is_error()

    def test_acceptable_variation_is_not_an_error(self):
        for c in ("regional", "informal", "formal", "unusual", "acceptable"):
            assert not GrammarErrorModel(original="x", classification=c).is_error()

    def test_error_classifications_subset(self):
        assert ERROR_CLASSIFICATIONS <= set(GRAMMAR_CLASSIFICATIONS)


class TestSelectErrors:
    def test_none_analysis(self):
        assert _select_errors(None) == []

    def test_wrong_high_confidence_kept(self):
        errs = _select_errors(
            _analysis(
                original="Yo soy hambre",
                classification="wrong",
                confidence=0.9,
                rule="ser_vs_tener",
            )
        )
        assert len(errs) == 1
        assert errs[0]["rule"] == "ser_vs_tener"

    def test_regional_dropped(self):
        assert (
            _select_errors(
                _analysis(original="vos querés", classification="regional", confidence=0.9)
            )
            == []
        )

    def test_low_confidence_error_abstained(self):
        assert _select_errors(_analysis(original="x", classification="wrong", confidence=0.2)) == []

    def test_empty_original_skipped(self):
        assert _select_errors(_analysis(original="", classification="wrong", confidence=0.9)) == []


class TestToGrammarError:
    def test_preserves_legacy_keys_and_adds_taxonomy(self):
        model = GrammarErrorModel(
            original="o",
            correction="c",
            rule="r",
            explanation="e",
            severity="critical",
            classification="wrong",
            construction="con",
            confidence=0.8,
            alternatives=["alt"],
        )
        err = _to_grammar_error(model)
        # Legacy keys preserved.
        for key in ("original", "correction", "rule", "explanation", "severity"):
            assert key in err
        # Taxonomy added.
        assert err["classification"] == "wrong"
        assert err["construction"] == "con"
        assert err["confidence"] == 0.8
        assert err["alternatives"] == ["alt"]

    def test_construction_falls_back_to_rule(self):
        model = GrammarErrorModel(original="o", rule="ser_vs_estar", classification="wrong")
        err = _to_grammar_error(model)
        assert err["construction"] == "ser_vs_estar"


class TestTaxonomyLoader:
    def test_loads_spanish(self):
        tax = load_taxonomy("Spanish")
        assert "ser_vs_estar" in tax
        assert isinstance(tax["ser_vs_estar"], GrammarItem)
        assert tax["ser_vs_estar"].cefr == "A2"

    def test_loads_polish_high_morphology(self):
        tax = load_taxonomy("Polish")
        assert "genitive_case" in tax
        assert "verb_aspect" in tax

    def test_loads_italian(self):
        assert "passato_prossimo_vs_imperfetto" in load_taxonomy("Italian")

    def test_unknown_language_empty(self):
        assert load_taxonomy("Klingon") == {}

    def test_accepts_code_or_name(self):
        assert load_taxonomy("es") == load_taxonomy("Spanish")

    def test_get_and_list(self):
        assert get_construction("Spanish", "por_vs_para") is not None
        assert get_construction("Spanish", "nonexistent") is None
        assert len(list_constructions("Spanish")) >= 5

    def test_prerequisites_and_interferences_present(self):
        item = get_construction("Spanish", "preterite_vs_imperfect")
        assert item is not None
        assert "gender_agreement" in item.prerequisites
        assert item.common_interferences


class TestGrammarNodeStructured:
    async def test_acceptable_variation_not_flagged_end_to_end(self, monkeypatch):
        # The model classifies a regional form; the agent must not surface it.
        payload = (
            '{"errors": [{"original": "vos querés", "correction": "tú quieres",'
            ' "construction": "voseo", "classification": "regional", "confidence": 0.9}]}'
        )

        monkeypatch.setattr(grammar, "get_provider", lambda tier: _FakeProvider(payload))
        state = {"last_user_input": "vos querés café", "language": "Spanish", "cefr_level": "B1"}
        result = await grammar.grammar_node(state)
        assert result["grammar_errors"] == []

    async def test_genuine_error_flagged_with_taxonomy(self, monkeypatch):
        payload = (
            '{"errors": [{"original": "Yo soy hambre", "correction": "Yo tengo hambre",'
            ' "construction": "ser_vs_tener", "rule": "ser_vs_tener",'
            ' "classification": "wrong", "severity": "critical", "confidence": 0.95}]}'
        )

        monkeypatch.setattr(grammar, "get_provider", lambda tier: _FakeProvider(payload))
        state = {"last_user_input": "Yo soy hambre", "language": "Spanish", "cefr_level": "A2"}
        result = await grammar.grammar_node(state)
        assert len(result["grammar_errors"]) == 1
        assert result["grammar_errors"][0]["classification"] == "wrong"
        assert result["grammar_errors"][0]["construction"] == "ser_vs_tener"


class TestGrammarBenchmark:
    async def test_precision_benchmark_passes(self):
        from benchmarks.grammar_bench import bench_grammar_precision

        result = await bench_grammar_precision()
        assert result.passed
        assert result.metrics["false_correction_rate"] <= 0.1
        assert result.metrics["precision"] == 1.0


class TestEvidenceClassification:
    def test_classification_flows_to_event_assessment(self):
        from src.evidence.extractor import extract_grammar_events
        from src.evidence.provenance import Provenance

        errs = [
            {
                "rule": "voseo",
                "construction": "voseo",
                "original": "vos",
                "classification": "regional",
                "confidence": 0.8,
            },
            {
                "rule": "ser_vs_tener",
                "construction": "ser_vs_tener",
                "original": "soy hambre",
                "classification": "wrong",
                "severity": "critical",
                "confidence": 0.9,
            },
        ]
        events = extract_grammar_events("u1", "Spanish", errs, provenance=Provenance("t"))
        by_item = {e.item_id: e for e in events}
        assert by_item["voseo"].assessment == "regional"
        assert by_item["ser_vs_tener"].assessment == "incorrect"
