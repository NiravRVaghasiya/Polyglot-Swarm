"""Hand-labeled grammar dataset: (is_error, GrammarAnalysis) cases.

Each case is what a well-behaved grammar model would return for one sentence,
paired with a ground-truth label: should the tutor flag this as an error?
Spans the categories the plan (Phase 4/18) calls out — genuinely incorrect,
native-acceptable, regional, informal, idiomatic, and low-confidence/ambiguous
— plus enough cases per confidence band to make calibration meaningful.

No live model is called: this is the *policy* under test
(:func:`src.agents.grammar._select_errors`), not the LLM that would produce the
analysis in production. That keeps the suite deterministic and fast.
"""

from __future__ import annotations

from src.llm.schemas import GrammarAnalysis, GrammarErrorModel

#: Bump when cases are added/changed/removed, so a metrics regression can be
#: traced to "the dataset changed" vs. "the policy changed".
DATASET_VERSION = "2026.09.0"

# (is_error, analysis). is_error=True means the tutor SHOULD flag it;
# is_error=False means the model's proposal (if any) is a false correction the
# policy must suppress.
CASES: list[tuple[bool, GrammarAnalysis]] = [
    # --- Genuinely incorrect, high confidence -> should be flagged. ---
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
                    confidence=0.92,
                )
            ]
        ),
    ),
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
                    confidence=0.88,
                )
            ]
        ),
    ),
    (
        True,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Quiero que tu vienes",
                    correction="Quiero que vengas",
                    construction="subjunctive_trigger",
                    classification="wrong",
                    severity="moderate",
                    confidence=0.9,
                )
            ]
        ),
    ),
    (
        True,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Le vi a ella ayer en el parque",
                    correction="La vi a ella ayer en el parque",
                    construction="direct_object_pronoun",
                    classification="wrong",
                    severity="minor",
                    confidence=0.78,
                )
            ]
        ),
    ),
    # --- Native-acceptable: no deviations -> must NOT be flagged. ---
    (False, GrammarAnalysis(errors=[])),
    (False, GrammarAnalysis(errors=[])),
    (False, GrammarAnalysis(errors=[])),
    # --- Regional variant -> classified regional -> must NOT be flagged. ---
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="¿Vos querés café?",
                    correction="¿Tú quieres café?",
                    construction="voseo",
                    classification="regional",
                    confidence=0.82,
                )
            ]
        ),
    ),
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Vino p'acá temprano",
                    correction="Vino para acá temprano",
                    construction="regional_contraction",
                    classification="regional",
                    confidence=0.7,
                )
            ]
        ),
    ),
    # --- Informal but valid -> must NOT be flagged. ---
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="pa'l centro",
                    correction="para el centro",
                    construction="contraction",
                    classification="informal",
                    confidence=0.72,
                )
            ]
        ),
    ),
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="¿Qué onda?",
                    correction="¿Qué tal?",
                    construction="colloquialism",
                    classification="informal",
                    confidence=0.68,
                )
            ]
        ),
    ),
    # --- Idiom -> acceptable -> must NOT be flagged. ---
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
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Me costó un ojo de la cara",
                    correction="(idiom: it cost a fortune)",
                    construction="idiom",
                    classification="acceptable",
                    confidence=0.65,
                )
            ]
        ),
    ),
    # --- Ambiguous / low-confidence -> agent should abstain (not flag). ---
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Está bien así",
                    correction="Está bien de esta manera",
                    construction="register",
                    classification="wrong",
                    confidence=0.3,
                )
            ]
        ),
    ),
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="Lo hice de una",
                    correction="Lo hice inmediatamente",
                    construction="register",
                    classification="wrong",
                    confidence=0.42,
                )
            ]
        ),
    ),
    # --- Formal register, valid -> must NOT be flagged. ---
    (
        False,
        GrammarAnalysis(
            errors=[
                GrammarErrorModel(
                    original="¿Usted podría indicarme la dirección?",
                    correction="¿Podrías indicarme la dirección?",
                    construction="formality",
                    classification="formal",
                    confidence=0.55,
                )
            ]
        ),
    ),
]
