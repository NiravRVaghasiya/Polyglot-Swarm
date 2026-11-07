"""Calibrated correction confidence in ``_select_errors`` (per answering model)."""

from __future__ import annotations

import json
import logging

import pytest

from src.agents import grammar
from src.evaluation import calibration_maps as cm
from src.llm import governance
from src.llm.schemas import GrammarAnalysis, GrammarErrorModel

KEY = "ollama:test-model:1b"


def _analysis(*confidences: float) -> GrammarAnalysis:
    return GrammarAnalysis(
        errors=[
            GrammarErrorModel(original=f"err{i}", correction="ok", rule="r", confidence=c)
            for i, c in enumerate(confidences)
        ]
    )


def _write(directory, doc, key=KEY):
    path = directory / cm.map_filename(key)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def _histogram_doc(values=(0.9, 0.9, 0.9, 0.2, 0.2), key=KEY, split="dev"):
    """Low raw confidence -> likely right; high raw confidence -> likely wrong."""
    return {
        "calibration_version": cm.CALIBRATION_VERSION,
        "key": key,
        "status": cm.FITTED,
        "method": "histogram",
        "params": {"edges": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0], "values": list(values)},
        "dev_predictions": 40,
        "source": {"run_id": "r-dev", "split": split, "dataset_version": "v"},
    }


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    cm.clear_cache()
    monkeypatch.setattr(grammar, "_uncalibrated_logged", set())
    yield
    cm.clear_cache()


class TestMapPresent:
    def test_threshold_applies_to_the_calibrated_probability(self, tmp_path):
        _write(tmp_path, _histogram_doc())
        kept = grammar._select_errors(_analysis(0.3, 0.95), model_key=KEY, calibration_dir=tmp_path)
        # 0.3 maps to 0.9 (kept); 0.95 maps to 0.2 (dropped, though > 0.5 raw).
        assert [e["original"] for e in kept] == ["err0"]
        assert kept[0]["confidence"] == 0.9 and kept[0]["raw_confidence"] == 0.3

    def test_platt_map_is_applied(self, tmp_path):
        doc = {**_histogram_doc(), "method": "platt", "params": {"a": 1.0, "b": -3.0}}
        _write(tmp_path, doc)
        kept = grammar._select_errors(_analysis(0.9), model_key=KEY, calibration_dir=tmp_path)
        assert kept == []  # sigmoid(logit(0.9) - 3) = 0.30

    def test_node_uses_the_model_that_answered(self, tmp_path, monkeypatch):
        _write(tmp_path, _histogram_doc())
        monkeypatch.setattr(cm, "DEFAULT_DIR", tmp_path)

        class Answering:
            async def generate_structured(self, messages, schema, **kw):
                governance.note_answer("ollama", "test-model:1b", fallback=False)
                return _analysis(0.3, 0.95)

        monkeypatch.setattr(grammar, "get_provider", lambda tier: Answering())
        out = await_(
            grammar.grammar_node(
                {"last_user_input": "yo es cansado", "language": "Spanish", "grammar_errors": []}
            )
        )
        assert [e["original"] for e in out["grammar_errors"]] == ["err0"]


def await_(coro):
    import asyncio

    return asyncio.run(coro)


class TestMapAbsent:
    def test_raw_threshold_and_uncalibrated_log(self, tmp_path, caplog):
        caplog.set_level(logging.INFO, logger="polyglot.grammar")
        kept = grammar._select_errors(_analysis(0.3, 0.95), model_key=KEY, calibration_dir=tmp_path)
        assert [e["original"] for e in kept] == ["err1"]
        assert kept[0]["confidence"] == 0.95 and "raw_confidence" not in kept[0]
        assert f"{KEY} is uncalibrated" in caplog.text
        caplog.clear()
        grammar._select_errors(_analysis(0.9), model_key=KEY, calibration_dir=tmp_path)
        assert "uncalibrated" not in caplog.text  # logged once per model

    def test_unknown_model_is_uncalibrated(self, caplog):
        caplog.set_level(logging.INFO, logger="polyglot.grammar")
        kept = grammar._select_errors(_analysis(0.3, 0.95))
        assert [e["original"] for e in kept] == ["err1"]
        assert "unknown model is uncalibrated" in caplog.text

    def test_insufficient_dev_data_is_not_applied(self, tmp_path):
        doc = {k: v for k, v in _histogram_doc().items() if k not in ("method", "params")}
        _write(tmp_path, {**doc, "status": cm.INSUFFICIENT})
        kept = grammar._select_errors(_analysis(0.95), model_key=KEY, calibration_dir=tmp_path)
        assert kept[0]["confidence"] == 0.95


class TestCorruptMap:
    @pytest.mark.parametrize(
        "doc",
        [
            "{not json",
            json.dumps(["a", "list"]),
            json.dumps({**_histogram_doc(), "calibration_version": "other-0.1"}),
            json.dumps({**_histogram_doc(), "key": "ollama:someone-else"}),
            json.dumps({**_histogram_doc(), "method": "isotonic"}),
            json.dumps({**_histogram_doc(), "params": {"edges": [0, 1], "values": [1, 2, 3]}}),
            json.dumps({**_histogram_doc(), "params": {"edges": [0.0, 1.0], "values": [7.0]}}),
            json.dumps(_histogram_doc(split="test")),
            json.dumps({k: v for k, v in _histogram_doc().items() if k != "params"}),
        ],
    )
    def test_falls_back_to_the_raw_threshold_and_logs(self, tmp_path, caplog, doc):
        _write(tmp_path, doc)
        with caplog.at_level(logging.ERROR, logger="polyglot.calibration"):
            kept = grammar._select_errors(
                _analysis(0.3, 0.95), model_key=KEY, calibration_dir=tmp_path
            )
        assert [e["original"] for e in kept] == ["err1"]
        assert "ignoring calibration map" in caplog.text


class TestFitting:
    def test_refuses_anything_but_the_dev_split(self):
        pairs = [(0.9, True), (0.2, False)] * 10
        with pytest.raises(ValueError, match="dev split only"):
            cm.fit_map(KEY, pairs, {"split": "test"})

    def test_too_little_or_one_class_is_insufficient(self):
        two_classes = [(0.9, True)] * 14 + [(0.1, False)]
        assert cm.fit_map(KEY, two_classes, {"split": "dev"})["status"] == cm.FITTED
        assert cm.fit_map(KEY, [(0.9, True)] * 10, {"split": "dev"})["status"] == cm.INSUFFICIENT
        assert cm.fit_map(KEY, [(0.9, True)] * 30, {"split": "dev"})["status"] == cm.INSUFFICIENT

    def test_fitted_document_round_trips(self, tmp_path):
        pairs = [(0.9, False)] * 12 + [(0.4, True)] * 12 + [(0.9, True)] * 3
        doc = cm.fit_map(KEY, pairs, {"split": "dev", "run_id": "r"})
        assert doc["status"] == cm.FITTED and doc["method"] in {"platt", "histogram"}
        _write(tmp_path, doc)
        cal = cm.load_map(KEY, tmp_path)
        assert cal is not None and cal(0.4) > cal(0.9)
