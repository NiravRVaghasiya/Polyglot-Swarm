"""The speech benchmark harness, offline (no recogniser, no corpus)."""

from __future__ import annotations

import math

from evals.speech import analysis
from evals.speech.report import render


def _record(
    text, hyp, *, category="correct", accent="Spain", rate="+0%", snr=None, prob=0.9, issues=()
):
    words, t = [], 0.1
    for w in hyp.split():
        words.append({"text": w, "start": t, "end": t + 0.3, "probability": prob})
        t += 0.35
    return {
        "clip_id": f"{text}-{accent}-{rate}-{snr}",
        "text": text,
        "category": category,
        "accent": accent,
        "rate": rate,
        "snr_db": snr,
        "voice": "es-ES-AlvaroNeural",
        "error_span": "soy hambre" if category == "incorrect" else None,
        "fixes": ["tengo hambre"] if category == "incorrect" else [],
        "quality": {"issues": list(issues), "duration_s": 2.0},
        "total_ms": 1000.0,
        "transcript": {
            "text": hyp,
            "language": "es",
            "language_probability": 0.99,
            "confidence": prob,
            "segments": [{"start": 0.1, "end": t, "text": hyp, "words": words}] if words else [],
        },
    }


def test_wer_and_spearman():
    assert analysis.wer("el gato negro", "el gato negro") == (0, 3)
    assert analysis.wer("el gato negro", "el perro") == (2, 3)
    assert abs(analysis.spearman([(1, 1), (2, 2), (3, 3)]) - 1.0) < 1e-9
    assert abs(analysis.spearman([(1, 3), (2, 2), (3, 1)]) + 1.0) < 1e-9
    assert math.isnan(analysis.spearman([(1, 1)]))


def test_logistic_fit_recovers_direction():
    xs = [[x / 10] for x in range(-20, 21)]
    ys = [1 / (1 + math.exp(-2 * x[0])) for x in xs]
    w = analysis.fit_logistic(xs, ys, ridge=0.0)
    assert w[1] > 1.5


def test_synthetic_analysis_measures_fairness_preservation_and_abstention():
    records = [
        _record("yo tengo hambre", "yo tengo hambre"),
        _record("yo tengo hambre", "yo tengo hambre", accent="Mexico"),
        _record("yo tengo hambre", "yo tengo hombre", accent="Argentina"),
        _record("yo soy hambre", "yo soy hambre", category="incorrect"),
        _record("yo soy hambre", "yo tengo hambre", category="incorrect", accent="Mexico"),
        {
            **_record("", "gracias por ver el video", prob=0.2, issues=("noisy",)),
            "category": "noise_only",
        },
        {
            "clip_id": "sil",
            "category": "silence",
            "skipped": "no_speech_detected",
            "quality": {"issues": ["no_speech_detected"]},
        },
    ]
    out = analysis.analyse_synthetic(records)
    ff = out["false_unintelligible_rate_by_accent"]
    assert ff["Spain"]["value"] == 0.0 and ff["Argentina"]["value"] > 0
    ep = out["error_preservation"]
    assert ep["preserved"]["k"] == 1 and ep["auto_corrected"]["k"] == 1
    assert out["abstention"]["silence"]["no_graded_evidence"]["value"] == 1.0
    # A hallucinated transcript of pure noise must not yield graded evidence.
    assert out["abstention"]["noise_only"]["no_graded_evidence"]["value"] == 1.0
    md = render({"synthetic": out})
    assert "SYNTHETIC" in md and "No real learner study" in md
