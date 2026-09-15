"""Grammar precision / false-correction benchmark.

The plan (Phase 4/18) wants a grammar benchmark over native-acceptable
sentences, genuinely incorrect sentences, dialectal variants, informal
language, idioms, and ambiguous cases, targeting high precision and a low
false-correction rate.

This benchmark exercises the agent's *decision logic* — ``grammar._select_errors``
— deterministically: each labeled case supplies the structured analysis the
model would return for a sentence, and we measure whether the agent correctly
surfaces genuine errors and suppresses acceptable variation. It does not call a
live model, so it runs offline and reproducibly and isolates the
classification/abstention policy from model variance.

Metrics:
- precision            = TP / (TP + FP)   over "did the agent flag an error?"
- false_correction_rate= FP / (# acceptable cases)   (the key safety metric)
- recall               = TP / (TP + FN)
"""

from __future__ import annotations

from benchmarks.harness import BenchmarkResult
from src.agents.grammar import _select_errors
from src.llm.schemas import GrammarAnalysis, GrammarErrorModel

# A tiny, hand-labeled dataset. Each case is (label, analysis) where label is
# True if the sentence genuinely contains an error the tutor SHOULD flag, and
# the analysis is what a well-behaved model returns for that sentence.
#
# The cases span the categories the plan calls out: genuinely incorrect,
# native-acceptable, dialectal/regional, informal, idiom, and ambiguous.
_CASES: list[tuple[bool, GrammarAnalysis]] = [
    # Genuinely incorrect -> should be flagged.
    (
        True,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Yo soy hambre",
                    correction="Yo tengo hambre",
                    construction="ser_vs_tener",
                    classification="wrong",
                    severity="critical",
                    confidence=0.95,
                )
            ]
        ),
    ),
    (
        True,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="la casa blanco",
                    correction="la casa blanca",
                    construction="gender_agreement",
                    classification="wrong",
                    severity="moderate",
                    confidence=0.9,
                )
            ]
        ),
    ),
    # Native-acceptable -> model returns no deviations -> must NOT be flagged.
    (False, GrammarAnalysis(errors=[])),
    # Regional variant -> classified regional -> must NOT be flagged.
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="¿Vos querés café?",
                    correction="¿Tú quieres café?",
                    construction="voseo",
                    classification="regional",
                    confidence=0.8,
                )
            ]
        ),
    ),
    # Informal but valid -> classified informal -> must NOT be flagged.
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="pa'l centro",
                    correction="para el centro",
                    construction="contraction",
                    classification="informal",
                    confidence=0.7,
                )
            ]
        ),
    ),
    # Idiom -> acceptable -> must NOT be flagged.
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="tomar el pelo",
                    correction="(idiom: to tease)",
                    construction="idiom",
                    classification="acceptable",
                    confidence=0.6,
                )
            ]
        ),
    ),
    # Ambiguous / low-confidence -> agent should abstain (not flag).
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Está bien así",
                    correction="Está bien de esta manera",
                    construction="register",
                    classification="wrong",
                    confidence=0.3,  # below the abstain threshold
                )
            ]
        ),
    ),
    # Genuine error, high confidence -> flagged.
    (
        True,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Ayer voy al cine",
                    correction="Ayer fui al cine",
                    construction="preterite_vs_present",
                    classification="wrong",
                    severity="moderate",
                    confidence=0.85,
                )
            ]
        ),
    ),
]

# The false-correction rate we require the policy to stay at or below.
_MAX_FALSE_CORRECTION_RATE = 0.1


async def bench_grammar_precision() -> BenchmarkResult:
    """Measure precision, recall, and false-correction rate of the grammar policy."""
    tp = fp = fn = 0
    acceptable = 0
    for is_error, analysis in _CASES:
        flagged = bool(_select_errors(analysis))
        if not is_error:
            acceptable += 1
        if is_error and flagged:
            tp += 1
        elif is_error and not flagged:
            fn += 1
        elif not is_error and flagged:
            fp += 1

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    false_correction_rate = fp / acceptable if acceptable else 0.0

    passed = false_correction_rate <= _MAX_FALSE_CORRECTION_RATE
    return BenchmarkResult(
        name="grammar_precision",
        passed=passed,
        duration_ms=0.0,
        metrics={
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "false_correction_rate": round(false_correction_rate, 3),
            "cases": len(_CASES),
        },
        detail=f"tp={tp} fp={fp} fn={fn} (target FCR<={_MAX_FALSE_CORRECTION_RATE})",
    )
