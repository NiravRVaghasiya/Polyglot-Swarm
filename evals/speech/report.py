"""Markdown rendering of the speech benchmark, labelled by data type."""

from __future__ import annotations

import math
from typing import Any


def _f(v: Any, d: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:.{d}f}" if isinstance(v, float) else str(v)


def _ci(e: dict[str, Any], key: str = "spearman") -> str:
    lo, hi = e["ci95"]
    return f"{_f(e[key])} [{_f(lo)}, {_f(hi)}] (n={e['n']})"


def _p(e: dict[str, Any]) -> str:
    lo, hi = e["ci95"]
    return f"{_f(e['value'])} [{_f(lo)}, {_f(hi)}] ({e['k']}/{e['n']})"


def render(data: dict[str, Any]) -> str:
    lines = ["# Speech assessment benchmark", ""]
    so = data.get("speechocean762")
    if so:
        lines += [
            "## speechocean762 — external, expert-labelled (English read-aloud, Mandarin-L1)",
            "",
            "> Five experts' scores from the published corpus (CC BY 4.0). Learners are "
            "Mandarin-L1 children and adults reading English. These results do not transfer "
            "to other languages, L1s or free speech.",
            "",
            f"- Clips: {so['counts']}",
            f"- Corpus WER (Whisper base, test): {_f(so['transcription']['overall']['corpus_wer'])}",  # noqa: E501
        ]
        for g, v in so["transcription"]["by_age_group"].items():
            lines.append(f"  - {g}: corpus WER {_f(v['corpus_wer'])}")
        for g, v in so["transcription"]["by_gender"].items():
            lines.append(f"  - {g}: corpus WER {_f(v['corpus_wer'])}")
        fl = so["fluency"]
        lines += [
            "",
            "### Fluency vs expert fluency (test)",
            "",
            f"- Scored by the shipped gates: {_p(fl['coverage'])}; "
            f"abstained: {fl['abstained_by_reason']}",
            f"- Fitted map ({so['fluency_map']['fitted_on']}) Spearman: {_ci(fl['audio_model']['spearman'])}; "  # noqa: E501
            f"MAE (0–10): {_ci(fl['audio_model']['mae_0_10'], 'mean')}",
            f"- Text-only baseline (reference length) Spearman: {_ci(fl['baseline_text_only']['spearman'])}; "  # noqa: E501
            f"MAE: {_ci(fl['baseline_text_only']['mae_0_10'], 'mean')}",
            f"- Constant baseline MAE: {_ci(fl['baseline_constant']['mae_0_10'], 'mean')}",
            f"- Expert fluency distribution: {fl['expert_distribution']}",
            "- Single measures vs expert fluency:",
        ]
        for k, v in fl["measures_vs_expert"].items():
            lines.append(f"  - {k}: {_ci(v)}")
        for g, v in fl["by_age_group"].items():
            lines.append(f"- Fluency map, {g}: {_ci(v)}")
        it = so["intelligibility"]
        lines += [
            "",
            "### Intelligibility (ASR-recognised target words) vs experts (test)",
            "",
            f"- vs sentence accuracy: {_ci(it['vs_expert_accuracy'])}",
            f"- vs completeness: {_ci(it['vs_expert_completeness'])}",
            "- Words flagged 'not recognised', by expert word accuracy:",
        ]
        for k, v in it["word_flag_rate"].items():
            lines.append(f"  - {k}: {_p(v)}")
        lines.append(
            "- False corrections (flagged words experts rated acceptable): "
            f"{_p(it['false_correction_rate'])}"
        )
        for g, d in it["word_flag_rate_by_age_group"].items():
            lines.append(f"  - {g}: " + ", ".join(f"{k} {_f(v['value'])}" for k, v in d.items()))
        pp = so["pronunciation_proxy"]
        lines += [
            "",
            "### Pronunciation proxy gate (word probability vs expert word accuracy)",
            "",
            f"- dev: {_ci(pp['dev'])}; test: {_ci(pp['test'])}; gate {pp['gate']}; "
            f"passes on dev: {pp['passes_gate_on_dev']}; on test: {pp['passes_gate_on_test']}",
            "",
            "### Abstention quality",
            "",
            f"- transcript confidence vs utterance WER: {_ci(so['abstention']['confidence_vs_wer'])}",  # noqa: E501
            f"- coverage at threshold {so['abstention']['threshold']}: {_p(so['abstention']['coverage'])}",  # noqa: E501
            f"- WER kept: {_ci(so['abstention']['wer_kept'], 'mean')}; "
            f"WER abstained: {_ci(so['abstention']['wer_abstained'], 'mean')}",
            "- recogniser repetition loops (dev+test): "
            f"{_p(so['abstention']['repetition_loops'])}, "
            f"{so['abstention']['repetition_loops_above_confidence_threshold']} of them above the "
            "confidence threshold (caught only by the compression-ratio gate)",
            "",
            f"Performance (CPU, Whisper base): {so['performance']}",
            "",
        ]
    syn = data.get("synthetic")
    if syn:
        lines += [
            "## Synthetic Spanish speech — SYNTHETIC (Edge TTS), no expert labels",
            "",
            "> Native synthetic voices: every word is pronounced correctly, so this measures "
            "the recogniser and pipeline, not learners.",
            "",
            f"- WER by accent: { {k: _f(v['corpus_wer']) for k, v in syn['wer_by_accent'].items()} }",  # noqa: E501
            f"- WER by rate: { {k: _f(v['corpus_wer']) for k, v in syn['wer_by_rate'].items()} }",
            f"- WER by SNR: { {k: _f(v['corpus_wer']) for k, v in syn['wer_by_snr'].items()} }",
            "- False 'not intelligible' rate on correctly pronounced words, by accent:",
        ]
        for k, v in syn["false_unintelligible_rate_by_accent"].items():
            lines.append(f"  - {k}: {_p(v)}")
        ep = syn["error_preservation"]
        lines += [
            f"- Learner grammar errors kept by the recogniser: {_p(ep['preserved'])}; "
            f"auto-corrected: {_p(ep['auto_corrected'])}; other: {_p(ep['other'])}",
            f"- Abstention: {syn['abstention']}",
            f"- Noisy speech flagged 'noisy', by SNR: { {k: _f(v['value']) for k, v in syn['noisy_speech_flagged'].items()} }",  # noqa: E501
            f"- Latency: {syn['performance']}",
            "",
        ]
    fmt = data.get("formats")
    if fmt:
        lines += [
            "## Formats and edge cases — SYNTHETIC (offline Windows TTS, English)",
            "",
            "| format | decoded | median latency ms | mean WER |",
            "|---|---|---|---|",
        ]
        for k, v in fmt["by_format"].items():
            lines.append(
                f"| {k} | {v['decoded']}/{v['clips']} | {_f(v['latency_ms_median'], 0)} | {_f(v['mean_wer'])} |"  # noqa: E501
            )
        lines += ["", "| edge case | accepted | code / issues |", "|---|---|---|"]
        for e in fmt["edge_cases"]:
            lines.append(f"| {e['case']} | {e['accepted']} | {e.get('code') or e.get('issues')} |")
        lines.append("")
    lines.append(
        "No real learner study has been run. No Spanish expert-labelled audio exists in "
        "this project; the speechocean762 results are the only expert comparison."
    )
    return "\n".join(lines) + "\n"
