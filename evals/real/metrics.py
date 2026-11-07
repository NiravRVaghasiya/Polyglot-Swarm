"""Aggregate scored outcomes into metrics with explicit denominators and CIs.

Every proportion is reported as ``{"value", "numerator", "denominator",
"ci95"}`` (Wilson interval), so a reader always sees the sample size behind a
number. Statistics that are not simple proportions (F1, ECE, AURC) get a
seeded bootstrap interval over cases. Quality metrics are computed only over
calls that *succeeded*; failed calls are counted separately as execution
failures and never as "no error found".

Metric definitions (denominators in brackets):

Grammar detection, case level — ambiguous cases excluded:
- precision = TP / (TP + FP) [cases where an error was surfaced]
- recall = TP / (TP + FN) [cases labeled as containing an error]
- false_correction_rate = FP / (FP + TN) [cases labeled error-free]
- missed_error_rate = FN / (TP + FN) [cases labeled as containing an error]
- localization_rate = localized / TP [true detections whose span matches]
- span precision = matched surfaced errors / surfaced errors [all surfaced]
- span recall = matched expected errors / expected errors [all expected errors]
- correction_accuracy / construction_accuracy [surfaced errors matching an expected span]
- acceptable_alternative_recognition, dialect_acceptance, register_acceptance:
  share *not* flagged [error-free cases of that category]
- register_label_agreement: share where the model reported the deviation with an
  accepted label (e.g. "informal") [formal/informal cases]
- context_inappropriate_recall, vocabulary_misuse_recall [error cases of that category]
- ambiguous_abstention_rate: share with nothing surfaced [ambiguous cases]
- adversarial_accuracy: detection correct [adversarial cases]

Structured output [all successful grammar calls / all entries in them]:
- schema_valid_rate, json_valid_rate, bare_list_rate, recoverable_rate
- missing_field_rate, invalid_field_rate, unsupported_assessment_rate [entries]

Calibration [proposed error-class deviations on non-ambiguous cases]:
correct = the case contains an error and the deviation localizes one.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from itertools import combinations
from typing import Any

from evals.real.schema import GrammarCase, VocabularyCase
from evals.real.scoring import GrammarOutcome, VocabularyOutcome
from src.evaluation.calibration import calibration_error, reliability_buckets
from src.evaluation.metrics import f1_score
from src.evaluation.statistics import (
    area_under_risk_coverage,
    bootstrap_ci,
    brier_score,
    cohens_kappa,
    fit_histogram_binning,
    fit_platt,
    mcnemar_exact,
    risk_coverage,
    wilson_interval,
)


def proportion(num: int, den: int) -> dict[str, Any]:
    lo, hi = wilson_interval(num, den)
    return {
        "value": round(num / den, 4) if den else None,
        "numerator": num,
        "denominator": den,
        "ci95": [round(lo, 4), round(hi, 4)] if den else None,
    }


def _r(x: float) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 4)


def _boot(
    items: Sequence[Any], stat: Callable[[Sequence[Any]], float], seed: int, samples: int
) -> list[float | None] | None:
    if not items:
        return None
    lo, hi = bootstrap_ci(items, stat, samples=samples, seed=seed)
    return [_r(lo), _r(hi)]


def grammar_metrics(
    outcomes: list[GrammarOutcome],
    cases: dict[str, GrammarCase],
    *,
    seed: int = 0,
    samples: int = 2000,
) -> dict[str, Any]:
    ok = [o for o in outcomes if o.ok]
    labeled = [o for o in ok if cases[o.case_id].has_error is not None]
    tp = sum(1 for o in labeled if cases[o.case_id].has_error and o.predicted_error)
    fn = sum(1 for o in labeled if cases[o.case_id].has_error and not o.predicted_error)
    fp = sum(1 for o in labeled if not cases[o.case_id].has_error and o.predicted_error)
    tn = sum(1 for o in labeled if not cases[o.case_id].has_error and not o.predicted_error)

    def f1_of(sample: Sequence[GrammarOutcome]) -> float:
        t = sum(1 for o in sample if cases[o.case_id].has_error and o.predicted_error)
        p = sum(1 for o in sample if not cases[o.case_id].has_error and o.predicted_error)
        n = sum(1 for o in sample if cases[o.case_id].has_error and not o.predicted_error)
        prec = t / (t + p) if t + p else math.nan
        rec = t / (t + n) if t + n else math.nan
        if math.isnan(prec) or math.isnan(rec):
            return math.nan
        return f1_score(prec, rec)

    surfaced = [c for o in ok for c in o.candidates if c.surfaced]
    surfaced_matched = [c for c in surfaced if c.matched_expected is not None]
    expected_total = sum(o.expected_total for o in ok if cases[o.case_id].has_error)
    expected_matched = sum(o.expected_matched for o in ok if cases[o.case_id].has_error)
    true_detections = [o for o in labeled if cases[o.case_id].has_error and o.predicted_error]

    def subset(pred: Callable[[GrammarCase], bool]) -> list[GrammarOutcome]:
        return [o for o in ok if pred(cases[o.case_id])]

    def not_flagged(group: list[GrammarOutcome]) -> dict[str, Any]:
        return proportion(sum(1 for o in group if not o.predicted_error), len(group))

    def flagged(group: list[GrammarOutcome]) -> dict[str, Any]:
        return proportion(sum(1 for o in group if o.predicted_error), len(group))

    acceptable_alt = subset(lambda c: c.category == "acceptable_alternative")
    regional = subset(lambda c: c.category == "regional")
    register = subset(lambda c: c.category in ("formal", "informal"))
    synonyms = subset(lambda c: "synonym" in c.tags)
    context = subset(lambda c: c.category == "context_inappropriate")
    vocab = subset(lambda c: c.category == "vocabulary_misuse")
    ambiguous = subset(lambda c: c.has_error is None)
    adversarial = subset(lambda c: c.category == "adversarial")

    p = tp / (tp + fp) if tp + fp else math.nan
    r = tp / (tp + fn) if tp + fn else math.nan
    return {
        "cases_scored": len(ok),
        "cases_labeled": len(labeled),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": proportion(tp, tp + fp),
        "recall": proportion(tp, tp + fn),
        "f1": {
            "value": _r(f1_score(p, r)) if not (math.isnan(p) or math.isnan(r)) else None,
            "ci95": _boot(labeled, f1_of, seed, samples),
            "denominator": len(labeled),
        },
        "false_correction_rate": proportion(fp, fp + tn),
        "missed_error_rate": proportion(fn, tp + fn),
        "accuracy": proportion(tp + tn, len(labeled)),
        "localization_rate": proportion(
            sum(1 for o in true_detections if o.localized), len(true_detections)
        ),
        "span_precision": proportion(len(surfaced_matched), len(surfaced)),
        "span_recall": proportion(expected_matched, expected_total),
        "correction_accuracy": proportion(
            sum(1 for c in surfaced_matched if c.correction_ok), len(surfaced_matched)
        ),
        "construction_accuracy": proportion(
            sum(1 for c in surfaced_matched if c.construction_ok), len(surfaced_matched)
        ),
        "acceptable_alternative_recognition": not_flagged(acceptable_alt),
        "synonym_recognition": not_flagged(synonyms),
        "dialect_acceptance": not_flagged(regional),
        "register_acceptance": not_flagged(register),
        "register_label_agreement": proportion(
            sum(1 for o in register if o.reported_acceptable_class), len(register)
        ),
        "context_inappropriate_recall": flagged(context),
        "vocabulary_misuse_recall": flagged(vocab),
        "ambiguous_abstention_rate": not_flagged(ambiguous),
        "adversarial_accuracy": proportion(
            sum(1 for o in adversarial if o.detection_correct), len(adversarial)
        ),
    }


def structured_metrics(outcomes: list[GrammarOutcome]) -> dict[str, Any]:
    ok = [o for o in outcomes if o.ok]
    entries = sum(len(o.structure.entries) for o in ok)
    missing_by_field: dict[str, int] = defaultdict(int)
    for o in ok:
        for f, n in o.structure.missing_by_field.items():
            missing_by_field[f] += n
    not_valid = [o for o in ok if not o.structure.schema_valid]
    return {
        "calls": len(outcomes),
        "execution_failure_rate": proportion(len(outcomes) - len(ok), len(outcomes)),
        "json_valid_rate": proportion(sum(1 for o in ok if o.structure.json_valid), len(ok)),
        "schema_valid_rate": proportion(sum(1 for o in ok if o.structure.schema_valid), len(ok)),
        "bare_list_rate": proportion(
            sum(1 for o in ok if o.structure.top_level == "bare_list"), len(ok)
        ),
        "recoverable_rate": proportion(
            sum(1 for o in not_valid if o.structure.recoverable), len(not_valid)
        ),
        "missing_field_rate": proportion(
            sum(o.structure.entries_missing_field for o in ok), entries
        ),
        "invalid_field_rate": proportion(
            sum(o.structure.entries_invalid_field for o in ok), entries
        ),
        "unsupported_assessment_rate": proportion(
            sum(o.structure.entries_unsupported_assessment for o in ok), entries
        ),
        "missing_by_field": dict(missing_by_field),
    }


def evidence_metrics(
    outcomes: list[GrammarOutcome], cases: dict[str, GrammarCase]
) -> dict[str, Any]:
    ok = [o for o in outcomes if o.ok]
    graded = [g for o in ok for g in o.evidence["graded"]]
    matched = [g for g in graded if g["matched"]]
    expected = sum(o.expected_total for o in ok if cases[o.case_id].has_error)
    hit = sum(o.evidence["distinct_expected_hit"] for o in ok if cases[o.case_id].has_error)
    diff_graded = [g for g in matched if g["difficulty_ok"] is not None]
    by_expected_skill: dict[str, list[bool]] = defaultdict(list)
    for g in matched:
        by_expected_skill[str(g["expected_skill"])].append(bool(g["skill_ok"]))
    dup_cases = [o for o in ok if "duplicate_error" in cases[o.case_id].tags]
    return {
        "events": len(graded),
        "precision": proportion(len(matched), len(graded)),
        "recall": proportion(hit, expected),
        "skill_classification_accuracy": proportion(
            sum(1 for g in matched if g["skill_ok"]), len(matched)
        ),
        "skill_accuracy_by_expected_skill": {
            k: proportion(sum(v), len(v)) for k, v in sorted(by_expected_skill.items())
        },
        "subskill_classification_accuracy": proportion(
            sum(1 for g in matched if g["subskill_ok"]), len(matched)
        ),
        "difficulty_known_rate": proportion(
            sum(1 for g in matched if g["difficulty_known"]), len(matched)
        ),
        "difficulty_classification_accuracy": proportion(
            sum(1 for g in diff_graded if g["difficulty_ok"]), len(diff_graded)
        ),
        "duplicate_events_after_pipeline": sum(o.evidence["duplicate_events"] for o in ok),
        "duplicate_case_distinct_errors_recovered": proportion(
            sum(o.evidence["distinct_expected_hit"] for o in dup_cases),
            sum(o.expected_total for o in dup_cases),
        ),
    }


def _calibration_pairs(
    outcomes: list[GrammarOutcome], cases: dict[str, GrammarCase], *, raw: bool
) -> tuple[list[tuple[float, bool]], int]:
    pairs: list[tuple[float, bool]] = []
    missing = 0
    for o in outcomes:
        if not o.ok or cases[o.case_id].has_error is None:
            continue
        for c in o.candidates:
            if not c.is_error_class:
                continue
            correct = bool(cases[o.case_id].has_error) and c.matched_expected is not None
            conf = c.raw_confidence if raw else c.pipeline_confidence
            if conf is None:
                missing += 1
                continue
            pairs.append((conf, correct))
    return pairs, missing


def calibration_metrics(
    outcomes: list[GrammarOutcome],
    cases: dict[str, GrammarCase],
    *,
    dev_outcomes: list[GrammarOutcome] | None = None,
    dev_cases: dict[str, GrammarCase] | None = None,
    seed: int = 0,
    samples: int = 2000,
    min_dev_predictions: int = 15,
) -> dict[str, Any]:
    """Raw-LLM vs pipeline ("evaluator") confidence calibration on test data,
    plus calibration maps fitted on dev data only (if enough exists)."""
    raw_pairs, raw_missing = _calibration_pairs(outcomes, cases, raw=True)
    pipe_pairs, _ = _calibration_pairs(outcomes, cases, raw=False)

    def summary(pairs: list[tuple[float, bool]]) -> dict[str, Any]:
        if not pairs:
            return {"n": 0}
        return {
            "n": len(pairs),
            "mean_confidence": _r(sum(c for c, _ in pairs) / len(pairs)),
            "accuracy": proportion(sum(1 for _, y in pairs if y), len(pairs)),
            "ece": _r(calibration_error(pairs)),
            "ece_ci95": _boot(pairs, lambda s: calibration_error(list(s)), seed, samples),
            "brier": _r(brier_score(pairs)),
            "aurc": _r(area_under_risk_coverage(pairs)),
            "distinct_confidence_values": len({round(c, 3) for c, _ in pairs}),
            "reliability": [
                {
                    "bin": [round(b.low, 2), round(b.high, 2)],
                    "n": b.count,
                    "mean_confidence": round(b.mean_confidence, 3),
                    "accuracy": round(b.accuracy, 3),
                }
                for b in reliability_buckets(pairs)
            ],
            "risk_coverage": [[round(c, 3), round(a, 3)] for c, a in risk_coverage(pairs)],
        }

    result: dict[str, Any] = {
        "raw_llm_confidence": summary(raw_pairs),
        "raw_confidence_missing": proportion(raw_missing, raw_missing + len(raw_pairs)),
        "pipeline_confidence": summary(pipe_pairs),
        "note": (
            "Pipeline (evaluator) confidence = the value the learner model receives: the raw "
            "confidence when present, the schema default 1.0 when the model omitted it."
        ),
    }
    if dev_outcomes is not None and dev_cases is not None:
        dev_pairs, _ = _calibration_pairs(dev_outcomes, dev_cases, raw=False)
        if len(dev_pairs) < min_dev_predictions or len({y for _, y in dev_pairs}) < 2:
            result["fitted"] = {
                "status": "insufficient_dev_data",
                "dev_predictions": len(dev_pairs),
                "required": min_dev_predictions,
            }
        else:
            platt = fit_platt(dev_pairs)
            hist = fit_histogram_binning(dev_pairs)
            result["fitted"] = {
                "status": "fitted_on_dev_evaluated_on_test",
                "dev_predictions": len(dev_pairs),
                "platt": {"a": _r(platt.a), "b": _r(platt.b)},
                "platt_test": summary([(platt(c), y) for c, y in pipe_pairs]),
                "histogram_test": summary([(hist(c), y) for c, y in pipe_pairs]),
            }
    else:
        result["fitted"] = {"status": "no_dev_run"}
    return result


def downstream_metrics(
    outcomes: list[GrammarOutcome], cases: dict[str, GrammarCase]
) -> dict[str, Any]:
    """Does weighting evidence by confidence make learner-model input more reliable?

    Compares the precision of surfaced error evidence unweighted vs weighted by
    the confidence the learner model would use. A positive difference means
    confidence up-weights correct evidence relative to wrong evidence.
    """
    items: list[tuple[float, bool]] = []
    for o in outcomes:
        if not o.ok or cases[o.case_id].has_error is None:
            continue
        for c in o.candidates:
            if c.surfaced:
                items.append(
                    (
                        c.pipeline_confidence,
                        bool(cases[o.case_id].has_error) and c.matched_expected is not None,
                    )
                )
    if not items:
        return {"surfaced_evidence": 0}

    def unweighted(s: Sequence[tuple[float, bool]]) -> float:
        return sum(1 for _, y in s if y) / len(s) if s else math.nan

    def weighted(s: Sequence[tuple[float, bool]]) -> float:
        total = sum(c for c, _ in s)
        return sum(c for c, y in s if y) / total if total else math.nan

    return {
        "surfaced_evidence": len(items),
        "unweighted_precision": _r(unweighted(items)),
        "confidence_weighted_precision": _r(weighted(items)),
        "difference": _r(weighted(items) - unweighted(items)),
        "difference_ci95": _boot(items, lambda s: weighted(s) - unweighted(s), 7, 2000),
    }


def segment_accuracy(
    outcomes: list[GrammarOutcome], cases: dict[str, GrammarCase], key: Callable[[GrammarCase], str]
) -> dict[str, Any]:
    groups: dict[str, list[GrammarOutcome]] = defaultdict(list)
    for o in outcomes:
        if o.ok and o.detection_correct is not None:
            groups[key(cases[o.case_id])].append(o)
    return {
        k: proportion(sum(1 for o in v if o.detection_correct), len(v))
        for k, v in sorted(groups.items())
    }


def vocabulary_metrics(
    outcomes: list[VocabularyOutcome], cases: dict[str, VocabularyCase]
) -> dict[str, Any]:
    ok = [o for o in outcomes if o.ok]
    extracted = sum(len(o.extracted) for o in ok)
    empty_cases = [o for o in ok if cases[o.case_id].required_words == []]
    return {
        "calls": len(outcomes),
        "execution_failure_rate": proportion(len(outcomes) - len(ok), len(outcomes)),
        "schema_valid_rate": proportion(sum(1 for o in ok if o.schema_valid), len(ok)),
        "missing_field_rate": proportion(
            sum(o.entries_missing_field for o in ok), sum(o.entries for o in ok)
        ),
        "precision": proportion(sum(o.relevant_extracted for o in ok), extracted),
        "recall": proportion(sum(o.required_found for o in ok), sum(o.required_total for o in ok)),
        "forbidden_rate": proportion(sum(o.forbidden_extracted for o in ok), extracted),
        "translation_accuracy": proportion(
            sum(o.translations_ok for o in ok), sum(o.translations_checked for o in ok)
        ),
        "produced_vs_exposed_accuracy": proportion(
            sum(o.produced_ok for o in ok), sum(o.produced_checked for o in ok)
        ),
        "nothing_to_extract_clean": proportion(
            sum(1 for o in empty_cases if not o.extracted), len(empty_cases)
        ),
    }


def cost_latency(outcomes: Sequence[GrammarOutcome | VocabularyOutcome]) -> dict[str, Any]:
    ok = [o for o in outcomes if o.ok]
    lat = sorted(o.latency_ms for o in ok)

    def pct(q: float) -> float | None:
        if not lat:
            return None
        return round(lat[min(len(lat) - 1, int(q * (len(lat) - 1)))], 1)

    return {
        "calls_ok": len(ok),
        "latency_ms": {"p50": pct(0.5), "p90": pct(0.9), "max": lat[-1] if lat else None},
        "input_tokens": sum(o.input_tokens for o in ok),
        "output_tokens": sum(o.output_tokens for o in ok),
        "tokens_estimated_share": proportion(sum(1 for o in ok if o.tokens_estimated), len(ok)),
        "estimated_cost_usd": round(sum(o.cost_usd for o in ok), 6),
    }


def cross_provider(
    by_provider: dict[str, list[GrammarOutcome]], cases: dict[str, GrammarCase]
) -> dict[str, Any]:
    """Agreement, paired tests and systematic disagreements across providers
    (same prompt, same cases)."""
    keyed = {
        p: {o.case_id: o for o in outs if o.ok and o.repeat == 0} for p, outs in by_provider.items()
    }
    pairs = []
    for a, b in combinations(sorted(keyed), 2):
        common = sorted(set(keyed[a]) & set(keyed[b]))
        if not common:
            continue
        pa = [keyed[a][c].predicted_error for c in common]
        pb = [keyed[b][c].predicted_error for c in common]
        labeled = [c for c in common if cases[c].has_error is not None]
        b_ = sum(
            1
            for c in labeled
            if keyed[a][c].detection_correct and not keyed[b][c].detection_correct
        )
        c_ = sum(
            1
            for c in labeled
            if not keyed[a][c].detection_correct and keyed[b][c].detection_correct
        )
        pairs.append(
            {
                "providers": [a, b],
                "cases": len(common),
                "agreement": proportion(
                    sum(1 for x, y in zip(pa, pb, strict=True) if x == y), len(common)
                ),
                "kappa": _r(cohens_kappa(pa, pb)),
                "mcnemar": {
                    "a_only_correct": b_,
                    "b_only_correct": c_,
                    "p_value": _r(mcnemar_exact(b_, c_)),
                },
            }
        )
    common_all = set.intersection(*(set(v) for v in keyed.values())) if keyed else set()
    disagreements: list[dict[str, Any]] = []
    all_wrong: list[dict[str, Any]] = []
    for cid in sorted(common_all):
        preds = {p: keyed[p][cid].predicted_error for p in keyed}
        if len(set(preds.values())) > 1:
            disagreements.append(
                {"case_id": cid, "category": cases[cid].category, "predicted_error": preds}
            )
        if cases[cid].has_error is not None and all(
            not keyed[p][cid].detection_correct for p in keyed
        ):
            all_wrong.append(
                {"case_id": cid, "category": cases[cid].category, "text": cases[cid].text}
            )
    by_cat: dict[str, int] = defaultdict(int)
    for d in disagreements:
        by_cat[d["category"]] += 1
    return {
        "pairs": pairs,
        "cases_in_common": len(common_all),
        "disagreements": disagreements,
        "disagreements_by_category": dict(sorted(by_cat.items())),
        "all_providers_wrong": all_wrong,
    }


def consistency(outcomes: list[GrammarOutcome]) -> dict[str, Any] | None:
    """Run-to-run agreement of the detection decision across repeats."""
    by_case: dict[str, set[bool]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for o in outcomes:
        if o.ok:
            by_case[o.case_id].add(o.predicted_error)
            counts[o.case_id] += 1
    repeated = [c for c, n in counts.items() if n > 1]
    if not repeated:
        return None
    return proportion(sum(1 for c in repeated if len(by_case[c]) == 1), len(repeated))
