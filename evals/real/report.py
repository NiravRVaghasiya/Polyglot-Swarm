"""Score a run directory and write ``report.json`` + ``report.md``.

The report states up front what kind of result it is:

- run status — ``complete`` / ``partial`` / ``failed`` (from the runner);
- whether any provider was synthetic (then nothing in it is a real-model result);
- the datasets' validation status — when cases are not expert-validated, the
  quality-gate section says the gates are provisional.

Every metric carries its sample size and a 95% interval; gates pass or fail
only when the interval is entirely on one side of the threshold.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from evals.real.calibration import committed_calibration
from evals.real.config import EvalConfig
from evals.real.datasets import load_split
from evals.real.metrics import (
    calibration_metrics,
    consistency,
    cost_latency,
    cross_provider,
    downstream_metrics,
    evidence_metrics,
    grammar_metrics,
    proportion,
    segment_accuracy,
    structured_metrics,
    vocabulary_metrics,
)
from evals.real.runner import load_responses
from evals.real.schema import GrammarCase, VocabularyCase
from evals.real.scoring import (
    GrammarOutcome,
    VocabularyOutcome,
    inspect_grammar_json,
    score_grammar,
    score_vocabulary,
)
from src.evaluation.statistics import gate_decision, mcnemar_exact

PRODUCTION_PROMPT = "grammar@1"


def _cases(task: str, split: str, version: str) -> dict[str, Any]:
    manifest, cases = load_split(task, split, version)
    return {c.case_id: c for c in cases}


def score_run(run_dir: Path) -> dict[str, Any]:
    """Score every response of a run. Returns grouped outcomes + case maps."""
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    records = load_responses(run_dir)
    grammar_cases: dict[str, GrammarCase] = {}
    vocab_cases: dict[str, VocabularyCase] = {}
    ds = manifest["datasets"]
    if "grammar" in ds:
        grammar_cases = _cases("grammar", ds["grammar"]["split"], ds["grammar"]["version"])
    if "vocabulary" in ds:
        vocab_cases = _cases("vocabulary", ds["vocabulary"]["split"], ds["vocabulary"]["version"])
    grammar: dict[tuple[str, str], list[GrammarOutcome]] = defaultdict(list)
    vocab: dict[str, list[VocabularyOutcome]] = defaultdict(list)
    for rec in records:
        key = f"{rec['provider']}:{rec['model']}"
        if rec["task"] == "grammar" and rec["case_id"] in grammar_cases:
            grammar[(key, rec["prompt"])].append(score_grammar(grammar_cases[rec["case_id"]], rec))
        elif rec["task"] == "vocabulary" and rec["case_id"] in vocab_cases:
            vocab[key].append(score_vocabulary(vocab_cases[rec["case_id"]], rec))
    return {
        "manifest": manifest,
        "grammar": grammar,
        "vocabulary": vocab,
        "grammar_cases": grammar_cases,
        "vocab_cases": vocab_cases,
    }


def _completeness(manifest: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    planned = int(manifest["planned_calls_per_provider"])
    out = []
    for p in manifest["providers"]:
        key = f"{p['provider']}:{p['model']}"
        mine = [r for r in records if f"{r['provider']}:{r['model']}" == key]
        ok = sum(1 for r in mine if r.get("ok"))
        failures: dict[str, int] = defaultdict(int)
        for r in mine:
            if not r.get("ok"):
                failures[str(r.get("error_category"))] += 1
        if p["status"] != "available":
            state = f"unavailable ({p['status']})"
        elif ok == planned:
            state = "complete"
        elif ok == 0:
            state = "failed"
        else:
            state = "partial"
        out.append(
            {
                "provider": key,
                "probe_status": p["status"],
                "probe_detail": p.get("detail", ""),
                "state": state,
                "planned_calls": planned,
                "successful_calls": ok,
                "failed_calls": len(mine) - ok,
                "failures_by_category": dict(failures),
            }
        )
    return {"run_status": manifest["status"], "providers": out}


def _variant_comparison(
    grammar: dict[tuple[str, str], list[GrammarOutcome]], cases: dict[str, GrammarCase]
) -> list[dict[str, Any]]:
    out = []
    for (prov_key, prompt), outs in sorted(grammar.items()):
        if prompt == PRODUCTION_PROMPT:
            continue
        base = {o.case_id: o for o in grammar.get((prov_key, PRODUCTION_PROMPT), []) if o.ok}
        cand = {o.case_id: o for o in outs if o.ok}
        common = sorted(c for c in set(base) & set(cand) if cases[c].has_error is not None)
        b = sum(1 for c in common if base[c].detection_correct and not cand[c].detection_correct)
        c_ = sum(1 for c in common if not base[c].detection_correct and cand[c].detection_correct)
        out.append(
            {
                "provider": prov_key,
                "baseline": PRODUCTION_PROMPT,
                "variant": prompt,
                "cases": len(common),
                "baseline_accuracy": proportion(
                    sum(1 for c in common if base[c].detection_correct), len(common)
                ),
                "variant_accuracy": proportion(
                    sum(1 for c in common if cand[c].detection_correct), len(common)
                ),
                "baseline_only_correct": b,
                "variant_only_correct": c_,
                "mcnemar_p": round(mcnemar_exact(b, c_), 4),
            }
        )
    return out


def _gates(
    config: EvalConfig, per_provider: dict[str, Any], dataset_status: dict[str, Any]
) -> dict[str, Any]:
    expert = all(
        set(d.get("validation_status_counts", {})) <= {"expert_validated"}
        for d in dataset_status.values()
    )
    results = []
    for prov_key, metrics in sorted(per_provider.items()):
        for gate in config.gates:
            section, _, name = gate.metric.partition(".")
            m = metrics.get(section, {}).get(name)
            if not m or m.get("value") is None:
                decision, value, ci = "inconclusive", None, None
            else:
                value, ci = m["value"], m["ci95"]
                decision = gate_decision(value, (ci[0], ci[1]), gate.threshold, gate.direction)
            results.append(
                {
                    "provider": prov_key,
                    "metric": gate.metric,
                    "threshold": gate.threshold,
                    "direction": gate.direction,
                    "value": value,
                    "ci95": ci,
                    "decision": decision,
                }
            )
    return {
        "dataset_expert_validated": expert,
        "production_gate": "evaluated" if expert else "not_established",
        "note": None
        if expert
        else (
            "The benchmark datasets are not expert-validated (author_labeled), so these "
            "gate decisions are provisional and must not be used to approve a model for "
            "production learner assessment."
        ),
        "results": results,
    }


def _bare_list_sensitivity(
    records: list[dict[str, Any]],
    prov_key: str,
    gcases: dict[str, GrammarCase],
    *,
    seed: int,
    samples: int,
) -> dict[str, Any] | None:
    """Re-score as if bare-list answers had been wrapped as ``{"errors": [...]}``.

    The production parser reads a bare JSON list as "no errors", so a model
    that answers in that shape looks conservative. This counterfactual shows
    what the model actually said. It is diagnostic only: it is not what the
    app does, and gates never use it. Returns None when no answer needed it.
    """
    outs: list[GrammarOutcome] = []
    wrapped = 0
    for rec in records:
        if (
            rec["task"] != "grammar"
            or rec["prompt"] != PRODUCTION_PROMPT
            or f"{rec['provider']}:{rec['model']}" != prov_key
            or rec["case_id"] not in gcases
        ):
            continue
        structure = inspect_grammar_json(rec.get("response_text") or "")
        if structure.recoverable:
            wrapped += 1
            rec = {**rec, "response_text": json.dumps({"errors": structure.entries})}
        outs.append(score_grammar(gcases[rec["case_id"]], rec))
    if not wrapped:
        return None
    return {
        "wrapped_responses": wrapped,
        "grammar": grammar_metrics(outs, gcases, seed=seed, samples=samples),
    }


def build_report(run_dir: Path, dev_run_dir: Path | None = None) -> dict[str, Any]:
    scored = score_run(run_dir)
    manifest = scored["manifest"]
    config = EvalConfig.model_validate(manifest["config"])
    gcases: dict[str, GrammarCase] = scored["grammar_cases"]
    vcases: dict[str, VocabularyCase] = scored["vocab_cases"]
    grammar: dict[tuple[str, str], list[GrammarOutcome]] = scored["grammar"]

    dev_grammar: dict[tuple[str, str], list[GrammarOutcome]] = {}
    dev_cases: dict[str, GrammarCase] = {}
    if dev_run_dir is not None and (dev_run_dir / "manifest.json").exists():
        dev = score_run(dev_run_dir)
        if dev["manifest"]["datasets"].get("grammar", {}).get("version") == manifest[
            "datasets"
        ].get("grammar", {}).get("version"):
            dev_grammar, dev_cases = dev["grammar"], dev["grammar_cases"]

    seed, samples = config.bootstrap_seed, config.bootstrap_samples
    records = load_responses(run_dir)
    per_provider: dict[str, Any] = {}
    for (prov_key, prompt), outs in sorted(grammar.items()):
        if prompt != PRODUCTION_PROMPT:
            continue
        dev_outs = dev_grammar.get((prov_key, prompt))
        per_provider[prov_key] = {
            "grammar": grammar_metrics(outs, gcases, seed=seed, samples=samples),
            "structured": structured_metrics(outs),
            "evidence": evidence_metrics(outs, gcases),
            "calibration": calibration_metrics(
                outs,
                gcases,
                dev_outcomes=dev_outs,
                dev_cases=dev_cases if dev_outs else None,
                seed=seed,
                samples=samples,
            ),
            "downstream": downstream_metrics(outs, gcases),
            "by_language": segment_accuracy(outs, gcases, lambda c: c.language),
            "by_cefr": segment_accuracy(outs, gcases, lambda c: c.cefr_level),
            "by_difficulty": segment_accuracy(outs, gcases, lambda c: c.difficulty),
            "by_category": segment_accuracy(outs, gcases, lambda c: c.category),
            "consistency": consistency(outs),
            "cost_latency": cost_latency(outs),
            "bare_list_sensitivity": _bare_list_sensitivity(
                records, prov_key, gcases, seed=seed, samples=samples
            ),
            "committed_calibration": committed_calibration(
                prov_key,
                records,
                outs,
                gcases,
                split=manifest["datasets"].get("grammar", {}).get("split"),
                dataset_version=manifest["datasets"].get("grammar", {}).get("version"),
            ),
        }
    for prov_key, vouts in sorted(scored["vocabulary"].items()):
        per_provider.setdefault(prov_key, {})["vocabulary"] = vocabulary_metrics(vouts, vcases)
        per_provider[prov_key]["vocabulary_cost_latency"] = cost_latency(vouts)

    production = {k: v for (k, p), v in grammar.items() if p == PRODUCTION_PROMPT}
    report = {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "synthetic": manifest["synthetic"],
        "created_at": manifest["created_at"],
        "config_hash": manifest["config_hash"],
        "datasets": manifest["datasets"],
        "prompts": manifest["prompts"],
        "git": manifest["git"],
        "environment": manifest["environment"],
        "dev_run": None if dev_run_dir is None else dev_run_dir.name,
        "completeness": _completeness(manifest, records),
        "providers": per_provider,
        "cross_provider": cross_provider(production, gcases) if len(production) > 1 else None,
        "prompt_variants": _variant_comparison(grammar, gcases),
        "gates": _gates(config, per_provider, manifest["datasets"]),
    }
    return report


def _fmt(m: dict[str, Any] | None) -> str:
    if not m or m.get("value") is None:
        return "n/a"
    ci = m.get("ci95")
    extra = f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""
    den = f" (n={m['denominator']})" if "denominator" in m else ""
    return f"{m['value']:.3f}{extra}{den}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Real-model evaluation — run `{report['run_id']}`", ""]
    status = report["status"]
    lines.append(f"- **Run status:** {status}")
    lines.append(
        f"- **Synthetic:** {'YES — not a real-model result' if report['synthetic'] else 'no'}"
    )
    for task, d in report["datasets"].items():
        lines.append(
            f"- **Dataset:** {task} `{d['version']}` split `{d['split']}` ({d['cases']} cases, "
            f"sha256 `{d['sha256'][:12]}`), validation status {d['validation_status_counts']}"
        )
    lines.append(
        f"- **Config hash:** `{report['config_hash']}`; "
        f"git `{(report['git'].get('commit') or '')[:10]}`"
        f"{' (dirty)' if report['git'].get('dirty') else ''}"
    )
    lines.append(
        "- **Prompts:** "
        + ", ".join(f"`{k}` ({v['sha256'][:10]})" for k, v in report["prompts"].items())
    )
    if report.get("dev_run"):
        lines.append(f"- **Calibration maps fitted on dev run:** `{report['dev_run']}`")
    lines += [
        "",
        "## Providers",
        "",
        "| provider | probe | state | ok / planned | failures |",
        "|---|---|---|---|---|",
    ]
    for p in report["completeness"]["providers"]:
        lines.append(
            f"| {p['provider']} | {p['probe_status']} | {p['state']} | "
            f"{p['successful_calls']} / {p['planned_calls']} | {p['failures_by_category'] or '-'} |"
        )
    unavailable = [
        p for p in report["completeness"]["providers"] if p["probe_status"] != "available"
    ]
    if unavailable:
        lines += ["", "Unavailable providers were not evaluated (no results were substituted):", ""]
        for p in unavailable:
            lines.append(f"- {p['provider']}: {p['probe_status']} — {p['probe_detail'][:160]}")

    for prov_key, m in report["providers"].items():
        g = m.get("grammar")
        lines += ["", f"## {prov_key}", ""]
        if g:
            lines += [
                "### Grammar (production prompt `grammar@1`, case level, ambiguous excluded)",
                "",
                f"Confusion: {g['confusion']} over {g['cases_labeled']} labeled cases.",
                "",
                "| metric | value [95% CI] (n) |",
                "|---|---|",
            ]
            for name in (
                "precision",
                "recall",
                "false_correction_rate",
                "missed_error_rate",
                "accuracy",
                "localization_rate",
                "span_precision",
                "span_recall",
                "correction_accuracy",
                "construction_accuracy",
                "acceptable_alternative_recognition",
                "synonym_recognition",
                "dialect_acceptance",
                "register_acceptance",
                "register_label_agreement",
                "context_inappropriate_recall",
                "vocabulary_misuse_recall",
                "ambiguous_abstention_rate",
                "adversarial_accuracy",
            ):
                lines.append(f"| {name} | {_fmt(g[name])} |")
            f1 = g["f1"]
            lines.append(f"| f1 | {f1['value']} {f1['ci95']} (n={f1['denominator']}) |")
            s = m["structured"]
            lines += [
                "",
                "### Structured output",
                "",
                "| metric | value [95% CI] (n) |",
                "|---|---|",
            ]
            for name in (
                "execution_failure_rate",
                "json_valid_rate",
                "schema_valid_rate",
                "bare_list_rate",
                "recoverable_rate",
                "missing_field_rate",
                "invalid_field_rate",
                "unsupported_assessment_rate",
            ):
                lines.append(f"| {name} | {_fmt(s[name])} |")
            if s["missing_by_field"]:
                lines.append(f"\nMissing fields: {s['missing_by_field']}")
            sens = m.get("bare_list_sensitivity")
            if sens:
                sg = sens["grammar"]
                lines += [
                    "",
                    "Bare-list sensitivity (diagnostic, not app behaviour): wrapping "
                    f"{sens['wrapped_responses']} recoverable bare-list answers as "
                    '`{"errors": [...]}` gives confusion '
                    f"{sg['confusion']}, recall {_fmt(sg['recall'])}, "
                    f"false_correction_rate {_fmt(sg['false_correction_rate'])}, "
                    f"accuracy {_fmt(sg['accuracy'])}.",
                ]
            e = m["evidence"]
            lines += [
                "",
                "### Evidence extraction (production pipeline)",
                "",
                "| metric | value |",
                "|---|---|",
            ]
            for name in (
                "precision",
                "recall",
                "skill_classification_accuracy",
                "subskill_classification_accuracy",
                "difficulty_known_rate",
                "difficulty_classification_accuracy",
                "duplicate_case_distinct_errors_recovered",
            ):
                lines.append(f"| {name} | {_fmt(e[name])} |")
            lines.append(
                f"| duplicate_events_after_pipeline | {e['duplicate_events_after_pipeline']} |"
            )
            if e["skill_accuracy_by_expected_skill"]:
                lines.append(
                    "\nSkill accuracy by expected skill: "
                    + ", ".join(
                        f"{k}: {_fmt(v)}" for k, v in e["skill_accuracy_by_expected_skill"].items()
                    )
                )
            c = m["calibration"]
            lines += ["", "### Confidence calibration", ""]
            for label, key in (
                ("raw LLM", "raw_llm_confidence"),
                ("pipeline", "pipeline_confidence"),
            ):
                cs = c[key]
                if cs.get("n"):
                    lines.append(
                        f"- {label}: n={cs['n']}, mean confidence {cs['mean_confidence']}, "
                        f"accuracy {_fmt(cs['accuracy'])}, ECE {cs['ece']} {cs['ece_ci95']}, "
                        f"Brier {cs['brier']}, AURC {cs['aurc']}, "
                        f"distinct confidence values {cs['distinct_confidence_values']}"
                    )
                else:
                    lines.append(f"- {label}: no predictions")
            lines.append(f"- raw confidence missing: {_fmt(c['raw_confidence_missing'])}")
            fitted = c.get("fitted", {})
            if fitted.get("status") == "fitted_on_dev_evaluated_on_test":
                lines.append(
                    f"- Platt map (dev n={fitted['dev_predictions']}) on test: "
                    f"ECE {fitted['platt_test'].get('ece')}, "
                    f"Brier {fitted['platt_test'].get('brier')}; histogram: ECE "
                    f"{fitted['histogram_test'].get('ece')}, "
                    f"Brier {fitted['histogram_test'].get('brier')}"
                )
            else:
                lines.append(f"- fitted calibration: {fitted.get('status')} {fitted}")
            cc = m.get("committed_calibration") or {}
            if cc.get("status") == "evaluated_on_test":
                before, after = cc["before"], cc["after"]
                lines.append(
                    f"- committed map ({cc['map']['method']}, fitted on dev run "
                    f"{cc['map']['source_run']}, n={cc['map']['dev_predictions']}), applied "
                    f"offline to this run: ECE {cc['ece_before']} -> {cc['ece_after']}; "
                    f"false-correction rate {_fmt(before['false_correction_rate'])} -> "
                    f"{_fmt(after['false_correction_rate'])}; precision "
                    f"{_fmt(before['precision'])} -> {_fmt(after['precision'])}; recall "
                    f"{_fmt(before['recall'])} -> {_fmt(after['recall'])}"
                )
            else:
                lines.append(f"- committed calibration map: {cc.get('status', 'absent')}")
            d = m["downstream"]
            if d.get("surfaced_evidence"):
                lines.append(
                    f"- learner-model input: unweighted precision {d['unweighted_precision']}, "
                    f"confidence-weighted {d['confidence_weighted_precision']} "
                    f"(difference {d['difference']}, 95% CI {d['difference_ci95']})"
                )
            for seg in ("by_language", "by_cefr", "by_difficulty", "by_category"):
                lines += [
                    "",
                    f"### Detection accuracy {seg.replace('_', ' ')}",
                    "",
                    "| segment | accuracy [95% CI] (n) |",
                    "|---|---|",
                ]
                for k, v in m[seg].items():
                    lines.append(f"| {k} | {_fmt(v)} |")
            cl = m["cost_latency"]
            lines += [
                "",
                f"Latency p50/p90/max: {cl['latency_ms']['p50']}/{cl['latency_ms']['p90']}/"
                f"{cl['latency_ms']['max']} ms; tokens in/out {cl['input_tokens']}/"
                f"{cl['output_tokens']} (estimated share {_fmt(cl['tokens_estimated_share'])}); "
                f"estimated cost ${cl['estimated_cost_usd']}",
            ]
            if m.get("consistency"):
                lines.append(f"Run-to-run consistency: {_fmt(m['consistency'])}")
        v = m.get("vocabulary")
        if v:
            lines += [
                "",
                "### Vocabulary extraction",
                "",
                "| metric | value [95% CI] (n) |",
                "|---|---|",
            ]
            for name in (
                "execution_failure_rate",
                "schema_valid_rate",
                "missing_field_rate",
                "precision",
                "recall",
                "forbidden_rate",
                "translation_accuracy",
                "produced_vs_exposed_accuracy",
                "nothing_to_extract_clean",
            ):
                lines.append(f"| {name} | {_fmt(v[name])} |")

    cp = report.get("cross_provider")
    if cp:
        lines += [
            "",
            "## Cross-provider comparison (`grammar@1`)",
            "",
            "| providers | agreement | kappa | McNemar (a only / b only, p) |",
            "|---|---|---|---|",
        ]
        for p in cp["pairs"]:
            mc = p["mcnemar"]
            lines.append(
                f"| {' vs '.join(p['providers'])} | {_fmt(p['agreement'])} | {p['kappa']} | "
                f"{mc['a_only_correct']} / {mc['b_only_correct']}, p={mc['p_value']} |"
            )
        lines.append(f"\nDisagreements by category: {cp['disagreements_by_category']}")
        if cp["all_providers_wrong"]:
            lines.append("\nCases every provider got wrong:")
            for w in cp["all_providers_wrong"]:
                lines.append(f"- `{w['case_id']}` ({w['category']}): {w['text']}")
    if report["prompt_variants"]:
        lines += [
            "",
            "## Prompt variants (paired, cases with a situational context)",
            "",
            "| provider | variant | n | baseline acc | variant acc | McNemar p |",
            "|---|---|---|---|---|---|",
        ]
        for pv in report["prompt_variants"]:
            lines.append(
                f"| {pv['provider']} | {pv['variant']} | {pv['cases']} | "
                f"{_fmt(pv['baseline_accuracy'])} | "
                f"{_fmt(pv['variant_accuracy'])} | {pv['mcnemar_p']} |"
            )
    gates = report["gates"]
    lines += ["", "## Quality gates", ""]
    if gates["note"]:
        lines += [f"> {gates['note']}", ""]
    lines += [
        "| provider | metric | threshold | value [95% CI] | decision |",
        "|---|---|---|---|---|",
    ]
    for g in gates["results"]:
        op = "<=" if g["direction"] == "max" else ">="
        lines.append(
            f"| {g['provider']} | {g['metric']} | {op} {g['threshold']} | "
            f"{g['value']} {g['ci95']} | {g['decision']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(
    run_dir: Path, *, dev_run_dir: Path | None = None, record_history: bool = True
) -> Path:
    """Write ``report.json`` and ``report.md`` into the run directory."""
    if dev_run_dir is None:
        candidate = run_dir.parent / (run_dir.name.replace("-test", "-dev"))
        if candidate != run_dir and (candidate / "manifest.json").exists():
            dev_run_dir = candidate
    report = build_report(run_dir, dev_run_dir)
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    if record_history:
        from evals.real.regression import record_history as _record

        _record(report)
    return run_dir
