"""Scoring raw responses: structure inspection, production policy, matching,
metric denominators. Pure, no model calls."""

from __future__ import annotations

import json

from evals.real import metrics as agg
from evals.real.datasets import load_source
from evals.real.scoring import (
    construction_matches,
    correction_matches,
    inspect_grammar_json,
    score_grammar,
    score_vocabulary,
    spans_overlap,
)

_, _GRAMMAR = load_source("grammar")
G = {c.case_id: c for c in _GRAMMAR}
_, _VOCAB = load_source("vocabulary")
V = {c.case_id: c for c in _VOCAB}


def rec(
    text,
    *,
    ok=True,
    provider="ollama",
    model="m",
    case="es-001",
    task="grammar",
    prompt="grammar@1",
):
    return {
        "provider": provider,
        "model": model,
        "task": task,
        "case_id": case,
        "prompt": prompt,
        "repeat": 0,
        "ok": ok,
        "error_category": None if ok else "timeout",
        "response_text": text,
        "latency_ms": 1000.0,
        "input_tokens": 100,
        "output_tokens": 20,
        "tokens_estimated": False,
        "cost_usd": 0.0,
    }


def entry(
    original, correction, construction="ser_vs_estar", classification="wrong", confidence=0.9, **kw
):
    return {
        "original": original,
        "correction": correction,
        "construction": construction,
        "rule": construction,
        "explanation": "",
        "classification": classification,
        "severity": "moderate",
        "confidence": confidence,
        "alternatives": [],
        **kw,
    }


def obj(*entries):
    return json.dumps({"errors": list(entries)})


class TestMatching:
    def test_span_overlap(self):
        assert spans_overlap("Yo soy hambre", "soy hambre")
        assert spans_overlap("soy", "soy hambre")  # contained
        assert not spans_overlap("mesa", "soy hambre")

    def test_correction_and_construction(self):
        assert correction_matches("Yo tengo hambre", ["tengo hambre"])
        assert not correction_matches("Yo estoy hambriento", ["tengo hambre"])
        assert construction_matches("Ser vs Tener", ["tener_expressions", "ser_vs_tener"])
        assert not construction_matches("unknown", ["ser_vs_tener"])


class TestStructure:
    def test_object_is_schema_valid(self):
        s = inspect_grammar_json(obj(entry("soy hambre", "tengo hambre")))
        assert s.schema_valid and s.top_level == "object_with_list"

    def test_bare_list_fails_production_parse_but_is_recoverable(self):
        s = inspect_grammar_json(json.dumps([entry("soy hambre", "tengo hambre")]))
        assert s.json_valid and not s.schema_valid
        assert s.top_level == "bare_list" and s.recoverable

    def test_fenced_json_is_valid(self):
        s = inspect_grammar_json("```json\n" + obj() + "\n```")
        assert s.schema_valid

    def test_missing_and_invalid_fields(self):
        e = entry("x", "y", classification="totally_wrong", confidence=3)
        del e["severity"]
        s = inspect_grammar_json(json.dumps({"errors": [e]}))
        assert s.entries_missing_field == 1 and s.missing_by_field == {"severity": 1}
        assert s.entries_invalid_field == 1
        assert s.entries_unsupported_assessment == 1

    def test_prose_is_invalid(self):
        assert not inspect_grammar_json("There are no errors.").json_valid


class TestGrammarOutcome:
    def test_true_detection_localized(self):
        o = score_grammar(
            G["es-001"], rec(obj(entry("soy hambre", "tengo hambre", "ser_vs_tener")))
        )
        assert o.predicted_error and o.detection_correct and o.localized
        assert o.candidates[0].correction_ok and o.candidates[0].construction_ok
        assert o.evidence["events"] == 1

    def test_bare_list_counts_as_missed_error_like_production(self):
        o = score_grammar(G["es-001"], rec(json.dumps([entry("soy hambre", "tengo hambre")])))
        assert not o.predicted_error and o.detection_correct is False

    def test_regional_classification_is_not_a_correction(self):
        o = score_grammar(
            G["es-026"],
            rec(obj(entry("tenés", "tienes", "voseo", classification="regional")), case="es-026"),
        )
        assert not o.predicted_error and o.detection_correct
        assert o.reported_acceptable_class

    def test_low_confidence_is_dropped_by_policy(self):
        o = score_grammar(G["es-002"], rec(obj(entry("tengo", "x", confidence=0.3)), case="es-002"))
        assert not o.predicted_error  # production abstains below 0.5

    def test_false_correction_on_correct_text(self):
        o = score_grammar(G["es-002"], rec(obj(entry("tengo", "tengo hambre")), case="es-002"))
        assert o.predicted_error and o.detection_correct is False and o.spurious_surfaced == 1

    def test_missing_confidence_defaults_to_one_in_pipeline(self):
        e = entry("soy hambre", "tengo hambre")
        del e["confidence"]
        o = score_grammar(G["es-001"], rec(obj(e)))
        assert o.candidates[0].raw_confidence is None
        assert o.candidates[0].pipeline_confidence == 1.0

    def test_ambiguous_case_has_no_correctness(self):
        o = score_grammar(G["es-010"], rec(obj(), case="es-010"))
        assert o.detection_correct is None

    def test_duplicate_spans_collapse_in_pipeline(self):
        e = entry("soy hambre", "tengo hambre", "ser_vs_tener")
        o = score_grammar(G["es-001"], rec(obj(e, e)))
        assert o.evidence["events"] == 1 and o.evidence["duplicate_events"] == 0

    def test_vocabulary_misuse_is_recorded_as_grammar_skill(self):
        o = score_grammar(
            G["es-018"], rec(obj(entry("embarazada", "avergonzada", "false_friend")), case="es-018")
        )
        graded = o.evidence["graded"][0]
        assert graded["matched"] and graded["expected_skill"] == "vocabulary"
        assert (
            graded["skill_ok"] is False
        )  # the pipeline files every grammar-agent finding as grammar


class TestGrammarMetrics:
    def test_confusion_and_denominators(self):
        outs = [
            score_grammar(G["es-001"], rec(obj(entry("soy hambre", "tengo hambre")))),  # TP
            score_grammar(G["es-003"], rec(obj(), case="es-003")),  # FN
            score_grammar(G["es-002"], rec(obj(entry("tengo", "x")), case="es-002")),  # FP
            score_grammar(G["es-017"], rec(obj(), case="es-017")),  # TN
            score_grammar(G["es-010"], rec(obj(), case="es-010")),  # ambiguous, excluded
            score_grammar(G["es-004"], rec(None, ok=False, case="es-004")),  # failed call
        ]
        m = agg.grammar_metrics(outs, G, samples=200)
        assert m["confusion"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
        assert m["false_correction_rate"]["denominator"] == 2
        assert m["recall"]["value"] == 0.5
        assert m["ambiguous_abstention_rate"]["value"] == 1.0
        assert m["cases_scored"] == 5  # the failed call is not scored as "no error"
        s = agg.structured_metrics(outs)
        assert s["execution_failure_rate"]["numerator"] == 1

    def test_calibration_needs_dev_data(self):
        outs = [score_grammar(G["es-001"], rec(obj(entry("soy hambre", "tengo hambre"))))]
        cal = agg.calibration_metrics(outs, G, dev_outcomes=outs, dev_cases=G, samples=50)
        assert cal["fitted"]["status"] == "insufficient_dev_data"
        assert cal["raw_llm_confidence"]["n"] == 1

    def test_cross_provider_disagreement(self):
        a = [score_grammar(G["es-001"], rec(obj(entry("soy hambre", "tengo hambre")), model="a"))]
        b = [score_grammar(G["es-001"], rec(obj(), model="b"))]
        cp = agg.cross_provider({"ollama:a": a, "ollama:b": b}, G)
        assert cp["pairs"][0]["agreement"]["value"] == 0.0
        assert cp["disagreements"][0]["case_id"] == "es-001"


class TestVocabulary:
    def test_precision_recall_translation_and_produced(self):
        case = V["es-v05"]
        text = json.dumps(
            {
                "words": [
                    {
                        "word": "bufanda",
                        "translation": "scarf",
                        "pos": "noun",
                        "context_sentence": "x",
                    },
                    {
                        "word": "guantes",
                        "translation": "hats",
                        "pos": "noun",
                        "context_sentence": "x",
                    },
                    {
                        "word": "ayer",
                        "translation": "yesterday",
                        "pos": "adv",
                        "context_sentence": "x",
                    },
                ]
            }
        )
        o = score_vocabulary(
            case, rec(text, case="es-v05", task="vocabulary", prompt="vocabulary@1")
        )
        assert o.required_found == 2 and o.required_total == 2
        assert o.translations_ok == 1 and o.translations_checked == 2
        assert o.forbidden_extracted == 1
        assert o.produced_ok == 2  # both are in the learner's own text
        m = agg.vocabulary_metrics([o], V)
        assert m["precision"]["value"] == round(2 / 3, 4)

    def test_nothing_to_extract(self):
        o = score_vocabulary(V["es-v07"], rec('{"words": []}', case="es-v07", task="vocabulary"))
        assert o.extracted == [] and o.schema_valid
