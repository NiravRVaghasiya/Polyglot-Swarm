"""Offline scoring of stored speech-pipeline outputs (ADR-0034).

Every metric is computed from the raw JSONL that ``run.py`` wrote. The
production decision functions (``align_target``, ``fluency_measures``, the
assessors' abstention rules) are applied to the stored transcripts, so the
numbers describe the shipped logic.

Intervals: a seeded bootstrap for correlations and means, Wilson intervals
for proportions. Spearman correlations use average ranks for ties.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from typing import Any

from src.evaluation.statistics import bootstrap_ci, wilson_interval
from src.multimodal.speaking import (
    MIN_TRANSCRIPT_CONFIDENCE,
    MIN_WORDS_FOR_FLUENCY,
    SpeakingTask,
    align_target,
    assess_fluency,
    assess_intelligibility,
    fluency_measures,
    tokens,
)
from src.multimodal.transcription import Segment, Transcript, Word

SEED = 20261107
BOOT = 1000
FLUENCY_FEATURES = ("speech_rate_wpm", "pause_time_ratio", "mean_length_of_run", "repetitions")
#: Spearman a proxy must reach against expert word accuracy, on dev *and* on
#: the held-out test sample, before it may produce graded evidence.
PRONUNCIATION_GATE = 0.35


# --- helpers ---------------------------------------------------------------


def transcript_of(record: dict[str, Any]) -> Transcript | None:
    t = record.get("transcript")
    if not t:
        return None
    segments = [
        Segment(
            start=s["start"],
            end=s["end"],
            text=s["text"],
            avg_logprob=s.get("avg_logprob"),
            no_speech_prob=s.get("no_speech_prob"),
            words=[Word(w["text"], w["start"], w["end"], w.get("probability")) for w in s["words"]],
        )
        for s in t["segments"]
    ]
    return Transcript(
        text=t["text"],
        language=t.get("language"),
        language_probability=t.get("language_probability"),
        segments=segments,
        provider=t.get("provider", ""),
        model=t.get("model", ""),
    )


def wer(reference: str, hypothesis: str) -> tuple[int, int]:
    """(edit distance in words, reference length) on normalized tokens."""
    r, h = tokens(reference), tokens(hypothesis)
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[-1], len(r)


def _ranks(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2.0
        i = j + 1
    return out


def spearman(pairs: Sequence[tuple[float, float]]) -> float:
    if len(pairs) < 3:
        return math.nan
    rx, ry = _ranks([p[0] for p in pairs]), _ranks([p[1] for p in pairs])
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else math.nan


def corr_ci(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    lo, hi = bootstrap_ci(pairs, spearman, samples=BOOT, seed=SEED)
    return {"spearman": spearman(pairs), "ci95": [lo, hi], "n": len(pairs)}


def mean_ci(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"mean": math.nan, "ci95": [math.nan, math.nan], "n": 0}
    lo, hi = bootstrap_ci(values, lambda v: sum(v) / len(v), samples=BOOT, seed=SEED)
    return {"mean": sum(values) / len(values), "ci95": [lo, hi], "n": len(values)}


def proportion(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_interval(k, n) if n else (math.nan, math.nan)
    return {"value": k / n if n else math.nan, "ci95": [lo, hi], "k": k, "n": n}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


def by_group(
    records: list[dict[str, Any]], key: str, fn: Callable[[list[dict[str, Any]]], Any]
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(str(r.get(key)), []).append(r)
    return {g: fn(rs) for g, rs in sorted(groups.items())}


# --- fluency map ---------------------------------------------------------------


def fit_logistic(
    xs: list[list[float]], ys: list[float], *, ridge: float = 1.0, iters: int = 50
) -> list[float]:
    """Ridge logistic regression with fractional targets (Newton/IRLS)."""
    d = len(xs[0]) + 1
    w = [0.0] * d
    rows = [[1.0, *x] for x in xs]
    for _ in range(iters):
        grad = [ridge * w[k] if k else 0.0 for k in range(d)]
        hess = [[(ridge if (a == b and a) else 0.0) for b in range(d)] for a in range(d)]
        for x, y in zip(rows, ys, strict=True):
            z = sum(wk * xk for wk, xk in zip(w, x, strict=True))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            for a in range(d):
                grad[a] += (p - y) * x[a]
                for b in range(d):
                    hess[a][b] += p * (1 - p) * x[a] * x[b]
        step = _solve(hess, grad)
        w = [wk - sk for wk, sk in zip(w, step, strict=True)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(n)]


def production_gate(r: dict[str, Any]) -> str | None:
    """Why the shipped pipeline would not score fluency here (``None`` = scored)."""
    t = transcript_of(r)
    if t is None:
        return "no_transcript"
    if t.repetition_loop:
        return "repetition_loop"
    if (t.confidence or 0.0) < MIN_TRANSCRIPT_CONFIDENCE:
        return "low_confidence"
    m = fluency_measures(t.words)
    if not m or m["words"] < MIN_WORDS_FOR_FLUENCY:
        return "too_few_words"
    return None


def fluency_rows(
    records: list[dict[str, Any]],
) -> list[tuple[dict[str, float], float, dict[str, Any]]]:
    """(measures, expert fluency / 10, record) for clips production would score."""
    out = []
    for r in records:
        if production_gate(r) is not None:
            continue
        t = transcript_of(r)
        assert t is not None
        out.append((fluency_measures(t.words), r["expert"]["fluency"] / 10.0, r))
    return out


def fit_fluency_map(dev: list[dict[str, Any]]) -> dict[str, Any]:
    rows = fluency_rows(dev)
    feats: dict[str, dict[str, float]] = {}
    for f in FLUENCY_FEATURES:
        vals = [m[f] for m, _, _ in rows]
        mean = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / max(1, len(vals) - 1)) or 1.0
        feats[f] = {"mean": mean, "sd": sd}
    xs = [
        [(m[f] - feats[f]["mean"]) / feats[f]["sd"] for f in FLUENCY_FEATURES] for m, _, _ in rows
    ]
    w = fit_logistic(xs, [y for _, y, _ in rows])
    for k, f in enumerate(FLUENCY_FEATURES, start=1):
        feats[f]["coef"] = w[k]
    return {
        "fitted_on": f"speechocean762/train sample (n={len(rows)})",
        "intercept": w[0],
        "features": {f: {k: round(v, 6) for k, v in spec.items()} for f, spec in feats.items()},
    }


# --- speechocean ---------------------------------------------------------------


def analyse_speechocean(dev: list[dict[str, Any]], test: list[dict[str, Any]]) -> dict[str, Any]:
    from src.multimodal.speaking import fluency_value

    out: dict[str, Any] = {"data": "external_expert_labelled", "corpus": "speechocean762"}
    out["counts"] = {
        split: {
            "clips": len(rs),
            "transcribed": sum(1 for r in rs if r.get("transcript")),
            "rejected": sum(1 for r in rs if r.get("rejected")),
            "skipped_no_speech": sum(1 for r in rs if r.get("skipped")),
            "failed": sum(1 for r in rs if r.get("step", {}).get("status") == "failed"),
        }
        for split, rs in (("dev", dev), ("test", test))
    }
    tested = [r for r in test if r.get("transcript")]

    # 1. Transcription
    def corpus_wer(rs: list[dict[str, Any]]) -> dict[str, Any]:
        edits = [wer(r["reference"], r["transcript"]["text"]) for r in rs]
        per = [e / n for e, n in edits if n]
        return {
            "corpus_wer": sum(e for e, _ in edits) / max(1, sum(n for _, n in edits)),
            "utterance_wer": mean_ci(per),
        }

    out["transcription"] = {
        "overall": corpus_wer(tested),
        "by_age_group": by_group(tested, "age_group", corpus_wer),
        "by_gender": by_group(tested, "gender", corpus_wer),
    }

    # 2. Fluency
    fmap = fit_fluency_map(dev)
    out["fluency_map"] = fmap
    test_rows = fluency_rows(test)
    dev_rows = fluency_rows(dev)
    dev_mean = sum(y for _, y, _ in dev_rows) / len(dev_rows)
    measures_vs_expert = {
        f: corr_ci([(m[f], y) for m, y, _ in test_rows]) for f in FLUENCY_FEATURES
    }
    preds = [(fluency_value(m, fmap) or 0.0, y) for m, y, _ in test_rows]
    # Text-only baseline: the reference sentence's length only.
    xs = [[float(len(tokens(r["reference"])))] for _, _, r in dev_rows]
    mu = sum(x[0] for x in xs) / len(xs)
    sd = math.sqrt(sum((x[0] - mu) ** 2 for x in xs) / max(1, len(xs) - 1)) or 1.0
    wt = fit_logistic([[(x[0] - mu) / sd] for x in xs], [y for _, y, _ in dev_rows])

    def text_pred(r: dict[str, Any]) -> float:
        z = wt[0] + wt[1] * (len(tokens(r["reference"])) - mu) / sd
        return 1.0 / (1.0 + math.exp(-z))

    text_preds = [(text_pred(r), y) for _, y, r in test_rows]
    gates = [production_gate(r) for r in test]
    out["fluency"] = {
        "coverage": proportion(sum(1 for g in gates if g is None), len(test)),
        "abstained_by_reason": {
            g: sum(1 for x in gates if x == g) for g in sorted({x for x in gates if x})
        },
        "expert_distribution": {
            str(k): sum(1 for _, y, _ in test_rows if round(y * 10) == k) for k in range(11)
        },
        "measures_vs_expert": measures_vs_expert,
        "audio_model": {
            "spearman": corr_ci(preds),
            "mae_0_10": mean_ci([abs(p - y) * 10 for p, y in preds]),
        },
        "baseline_constant": {"mae_0_10": mean_ci([abs(dev_mean - y) * 10 for _, y in preds])},
        "baseline_text_only": {
            "spearman": corr_ci(text_preds),
            "mae_0_10": mean_ci([abs(p - y) * 10 for p, y in text_preds]),
        },
        "by_age_group": by_group(
            [r for _, _, r in test_rows],
            "age_group",
            lambda rs: corr_ci(
                [
                    (
                        fluency_value(fluency_measures(transcript_of(r).words), fmap) or 0.0,  # type: ignore[union-attr]
                        r["expert"]["fluency"] / 10.0,
                    )
                    for r in rs
                ]
            ),
        ),
    }

    # 3/4. Intelligibility and word flags
    sentence_pairs_acc, sentence_pairs_comp = [], []
    flags = {"perfect": [0, 0], "accented_correct": [0, 0], "mispronounced": [0, 0]}
    flags_by_age: dict[str, dict[str, list[int]]] = {}
    prob_pairs_dev: list[tuple[float, float]] = []
    prob_pairs_test: list[tuple[float, float]] = []
    for split, rs in (("dev", dev), ("test", test)):
        for r in rs:
            t = transcript_of(r)
            if t is None:
                continue
            align = align_target(r["reference"], t.words)
            words = r["expert"]["words"]
            if len(align) != len(words):
                continue  # tokenisation mismatch (rare); skip rather than misalign
            for a, w in zip(align, words, strict=True):
                p = (a["probability"] or 0.0) if a["recognised"] else 0.0
                (prob_pairs_dev if split == "dev" else prob_pairs_test).append((p, w["accuracy"]))
            if split != "test":
                continue
            ratio = sum(1 for a in align if a["recognised"]) / len(align)
            sentence_pairs_acc.append((ratio, r["expert"]["accuracy"]))
            sentence_pairs_comp.append((ratio, r["expert"]["completeness"]))
            grp = flags_by_age.setdefault(
                r["age_group"],
                {"perfect": [0, 0], "accented_correct": [0, 0], "mispronounced": [0, 0]},
            )
            for a, w in zip(align, words, strict=True):
                acc = w["accuracy"]
                cat = (
                    "perfect"
                    if acc >= 10
                    else ("accented_correct" if acc >= 7 else "mispronounced")
                )
                for bucket in (flags, grp):
                    bucket[cat][0] += int(not a["recognised"])
                    bucket[cat][1] += 1
    out["intelligibility"] = {
        "vs_expert_accuracy": corr_ci(sentence_pairs_acc),
        "vs_expert_completeness": corr_ci(sentence_pairs_comp),
        "word_flag_rate": {k: proportion(*v) for k, v in flags.items()},
        # Of the words a word-level "not recognised" correction would name,
        # the share experts rated acceptable (accuracy >= 7): false corrections.
        "false_correction_rate": proportion(
            flags["perfect"][0] + flags["accented_correct"][0],
            sum(v[0] for v in flags.values()),
        ),
        "word_flag_rate_by_age_group": {
            g: {k: proportion(*v) for k, v in d.items()} for g, d in sorted(flags_by_age.items())
        },
    }
    dev_corr = corr_ci(prob_pairs_dev)
    test_corr = corr_ci(prob_pairs_test)
    out["pronunciation_proxy"] = {
        "gate": PRONUNCIATION_GATE,
        "dev": dev_corr,
        "test": test_corr,
        "passes_gate_on_dev": bool(dev_corr["spearman"] >= PRONUNCIATION_GATE),
        "passes_gate_on_test": bool(test_corr["spearman"] >= PRONUNCIATION_GATE),
    }

    # 6. Abstention quality: does low transcript confidence predict errors?
    #    Production abstains below the confidence threshold *or* on a
    #    repetition loop (which confidence alone does not catch).
    conf_wer = []
    for r in tested:
        conf = r["transcript"].get("confidence")
        e, n = wer(r["reference"], r["transcript"]["text"])
        if conf is not None and n:
            loop = bool(transcript_of(r).repetition_loop)  # type: ignore[union-attr]
            conf_wer.append((conf, e / n, loop))
    kept = [w for c, w, loop in conf_wer if c >= MIN_TRANSCRIPT_CONFIDENCE and not loop]
    dropped = [w for c, w, loop in conf_wer if c < MIN_TRANSCRIPT_CONFIDENCE or loop]
    loops = [
        r
        for r in dev + test
        if r.get("transcript") and transcript_of(r).repetition_loop  # type: ignore[union-attr]
    ]
    out["abstention"] = {
        "confidence_vs_wer": corr_ci([(c, w) for c, w, _ in conf_wer]),
        "threshold": MIN_TRANSCRIPT_CONFIDENCE,
        "coverage": proportion(len(kept), len(conf_wer)),
        "wer_kept": mean_ci(kept),
        "wer_abstained": mean_ci(dropped),
        "repetition_loops": proportion(
            len(loops), sum(1 for r in dev + test if r.get("transcript"))
        ),
        "repetition_loops_above_confidence_threshold": sum(
            1
            for r in loops
            if (r["transcript"].get("confidence") or 0) >= MIN_TRANSCRIPT_CONFIDENCE
        ),
    }

    # 7. Performance
    lat = [r["total_ms"] for r in dev + test if r.get("transcript")]
    durations = [r["quality"]["duration_s"] for r in dev + test if r.get("quality")]
    out["performance"] = {
        "latency_ms_p50": percentile(lat, 0.5),
        "latency_ms_p90": percentile(lat, 0.9),
        "audio_s_p50": percentile(durations, 0.5),
        "real_time_factor_p50": percentile(
            [
                r["total_ms"] / 1000 / max(r["quality"]["duration_s"], 0.1)
                for r in dev + test
                if r.get("transcript")
            ],
            0.5,
        ),
        "cost_usd": 0.0,
        "failure_rate": proportion(
            sum(1 for r in dev + test if not r.get("transcript")), len(dev + test)
        ),
    }
    return out


# --- synthetic -------------------------------------------------------------------


def analyse_synthetic(records: list[dict[str, Any]]) -> dict[str, Any]:
    speech = [r for r in records if r.get("category") in ("correct", "incorrect")]
    clean = [r for r in speech if r.get("snr_db") is None and r.get("transcript")]
    out: dict[str, Any] = {"data": "synthetic_tts", "clips": len(records)}

    def wer_of(rs: list[dict[str, Any]]) -> dict[str, Any]:
        edits = [wer(r["text"], r["transcript"]["text"]) for r in rs if r.get("transcript")]
        return {
            "corpus_wer": sum(e for e, _ in edits) / max(1, sum(n for _, n in edits)),
            "clips": len(edits),
        }

    out["wer_by_accent"] = by_group(clean, "accent", wer_of)
    out["wer_by_rate"] = by_group(clean, "rate", wer_of)
    noisy_base = [
        r
        for r in speech
        if r.get("voice") in ("es-ES-AlvaroNeural", "es-MX-DaliaNeural") and r.get("rate") == "+0%"
    ]
    out["wer_by_snr"] = by_group(
        [
            {**r, "snr": "clean" if r.get("snr_db") is None else f"{r['snr_db']} dB"}
            for r in noisy_base
            if r.get("transcript")
        ],
        "snr",
        wer_of,
    )

    # Accent fairness: correctly pronounced (synthetic) words flagged as not intelligible.
    def false_flags(rs: list[dict[str, Any]]) -> dict[str, Any]:
        k = n = 0
        for r in rs:
            t = transcript_of(r)
            if t is None:
                continue
            a = align_target(r["text"], t.words)
            k += sum(1 for x in a if not x["recognised"])
            n += len(a)
        return proportion(k, n)

    out["false_unintelligible_rate_by_accent"] = by_group(clean, "accent", false_flags)

    # Error preservation: does the recogniser keep the learner's error?
    def preservation(rs: list[dict[str, Any]]) -> dict[str, Any]:
        kept = fixed = other = 0
        for r in rs:
            hyp = " ".join(tokens(r["transcript"]["text"]))
            span = " ".join(tokens(r.get("error_span") or ""))
            fixes = [" ".join(tokens(f)) for f in r.get("fixes") or []]
            if span and f" {span} " in f" {hyp} ":
                kept += 1
            elif any(f and f" {f} " in f" {hyp} " for f in fixes):
                fixed += 1
            else:
                other += 1
        n = kept + fixed + other
        return {
            "preserved": proportion(kept, n),
            "auto_corrected": proportion(fixed, n),
            "other": proportion(other, n),
        }

    incorrect_clean = [r for r in clean if r["category"] == "incorrect"]
    out["error_preservation"] = preservation(incorrect_clean)
    out["error_preservation_by_accent"] = by_group(incorrect_clean, "accent", preservation)

    # Abstention on silence / noise-only, using the production assessors.
    def emitted_dimensions(r: dict[str, Any]) -> int:
        if r.get("skipped") or r.get("rejected"):
            return 0
        t = transcript_of(r)
        if t is None or t.repetition_loop:
            return 0
        issues = (r.get("quality") or {}).get("issues", [])
        dims = [
            assess_fluency(t, language_code="es", quality_issues=issues),
            assess_intelligibility(
                t, SpeakingTask("read_aloud", "una frase cualquiera"), quality_issues=issues
            ),
        ]
        return sum(1 for d in dims if d.status.value == "ok")

    out["abstention"] = {
        kind: {
            "clips": sum(1 for r in records if r.get("category") == kind),
            "no_graded_evidence": proportion(
                sum(1 for r in records if r.get("category") == kind and emitted_dimensions(r) == 0),
                sum(1 for r in records if r.get("category") == kind),
            ),
            "transcribed_words": sum(
                len((transcript_of(r) or Transcript("", None, None, [], "", "")).words)
                for r in records
                if r.get("category") == kind
            ),
        }
        for kind in ("silence", "noise_only")
    }
    out["noisy_speech_flagged"] = by_group(
        [{**r, "snr": f"{r['snr_db']} dB"} for r in speech if r.get("snr_db") is not None],
        "snr",
        lambda rs: proportion(
            sum(1 for r in rs if "noisy" in (r.get("quality") or {}).get("issues", [])), len(rs)
        ),
    )
    lat = [r["total_ms"] for r in records if r.get("transcript")]
    out["performance"] = {
        "latency_ms_p50": percentile(lat, 0.5),
        "latency_ms_p90": percentile(lat, 0.9),
    }
    return out


def shuffle_seeded(xs: list[Any]) -> list[Any]:
    ys = xs[:]
    random.Random(SEED).shuffle(ys)
    return ys
