"""Speaking assessment from a transcript with word timing (ADR-0034).

Three dimensions, each with an explicit basis. A dimension abstains, with a
reason, when its evidence is insufficient.

``fluency`` (basis ``timing``) — observable measures only:

- speech rate (words per minute over the speaking span);
- articulation rate (words per second of speech, excluding pauses);
- silent pauses (word gaps of at least :data:`PAUSE_S`): count, rate, mean
  length, and long pauses (at least :data:`LONG_PAUSE_S`);
- mean length of run (words between pauses);
- repetitions (immediately repeated words or bigrams);
- filled pauses (``uh``, ``eh``, ``em``, ...), when the recogniser kept them.

``value`` maps these measures to ``[0, 1]`` with a fixed logistic map
(:data:`FLUENCY_MAP`). That map was fitted on a speechocean762 *training*
sample (expert fluency ratings of Mandarin-L1 adults and children reading
English) and evaluated on a disjoint *test* sample in ``evals/speech``
(Spearman 0.60 vs 0.13 for a text-only baseline; 0.42 for children).

- **English read-aloud** (the validated scope): the measures and the value
  are reported, with confidence :data:`VALIDATED_CONFIDENCE`.
- **Anything else** (other languages, free speech): the map is not
  validated, so the result is ``partial``: measures only, no score, recorded
  as practice exposure.

Whisper's word timing is approximate, so pause measures are approximate too.

``intelligibility`` (basis ``transcript``; read-aloud tasks only) — the
share of target words the recogniser heard as those words. This is
intelligibility *to an ASR model*, **not phonetic accuracy**, and the
benchmark shows the model is not accent-neutral: correctly pronounced words
are missed more often for some accents (Rioplatense and Colombian Spanish
voices about 4x more than Castilian) and for children, and about 3 in 4
"not recognised" words were rated correct by experts. So:

- no word-level corrections are given; feedback is one neutral,
  utterance-level note;
- confidence is :data:`INTELLIGIBILITY_CONFIDENCE` for English (moderate
  agreement with experts) and :data:`UNVALIDATED_CONFIDENCE` elsewhere.

It abstains:

- without a target text;
- on noisy audio;
- when the transcript confidence is too low to separate recogniser errors
  from learner errors.

``pronunciation`` (basis ``acoustic_proxy``) — the recogniser's word
probabilities on the target words. Assessed **only for languages where the
proxy has been validated against expert word-level ratings**
(:data:`PRONUNCIATION_VALIDATED`). Every other language abstains. This is not
a phoneme-level analysis, and the feedback says so.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from src.multimodal.contracts import DimensionResult, Status
from src.multimodal.transcription import Transcript, Word
from src.util import sigmoid as _sigmoid

PAUSE_S = 0.25
LONG_PAUSE_S = 1.0
MIN_WORDS_FOR_FLUENCY = 4
#: Below this transcription confidence, transcript-based judgments abstain.
MIN_TRANSCRIPT_CONFIDENCE = 0.55
#: Judgment reliability (``DimensionResult.confidence``). It describes the
#: assessor's validity only: transcription uncertainty travels separately as
#: the event's ``transcription_confidence``, so it is never counted twice.
VALIDATED_CONFIDENCE = 0.6
INTELLIGIBILITY_CONFIDENCE = 0.5
UNVALIDATED_CONFIDENCE = 0.3
#: (language, task_type) scopes the fluency map was validated on.
FLUENCY_VALIDATED: frozenset[tuple[str, str]] = frozenset({("en", "read_aloud")})
#: Languages where the word-probability pronunciation proxy passed the gate
#: (Spearman >= 0.35 against expert word accuracy on dev *and* held-out test).
#: English: dev 0.371, test 0.322 [0.292, 0.348] -> not validated. Empty
#: until a benchmark result justifies an entry; see docs/multimodal-assessment.md.
PRONUNCIATION_VALIDATED: frozenset[str] = frozenset()
#: Logistic fluency map: value = sigmoid(intercept + sum(coef * z(feature))).
#: Fitted by ``evals/speech`` (``analysis.fit_fluency_map``) on the dev sample;
#: features are standardized with the given means / SDs. Regenerate with
#: ``python -m evals.speech report`` and copy ``fluency_map`` from the JSON.
FLUENCY_MAP: dict[str, Any] = {
    "fitted_on": "speechocean762/train sample (n=232)",
    "intercept": 1.457687,
    "features": {
        "speech_rate_wpm": {"mean": 135.402568, "sd": 36.830085, "coef": 0.45238},
        "pause_time_ratio": {"mean": 0.02618, "sd": 0.067887, "coef": -0.168634},
        "mean_length_of_run": {"mean": 6.104526, "sd": 2.105674, "coef": -0.300469},
        "repetitions": {"mean": 0.017241, "sd": 0.130451, "coef": -0.009794},
    },
}
FILLERS = frozenset({"uh", "um", "uhm", "er", "erm", "eh", "em", "ehm", "mm", "hmm", "este", "ah"})


def norm_word(text: str) -> str:
    """Lowercase, strip punctuation and accents (for matching, not display)."""
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^\w']", "", t)


def tokens(text: str) -> list[str]:
    return [w for w in (norm_word(t) for t in text.split()) if w]


@dataclass(frozen=True)
class SpeakingTask:
    task_type: str = "free_speech"  # free_speech | read_aloud
    target_text: str | None = None
    cefr: str | None = None
    language: str | None = None


# --- fluency -----------------------------------------------------------------


def fluency_measures(words: list[Word]) -> dict[str, float]:
    """Observable fluency measures from timed words (empty dict if < 2 words)."""
    spoken = [w for w in words if norm_word(w.text)]
    if len(spoken) < 2:
        return {}
    span = max(spoken[-1].end - spoken[0].start, 1e-3)
    gaps = [max(0.0, b.start - a.end) for a, b in zip(spoken, spoken[1:], strict=False)]
    pauses = [g for g in gaps if g >= PAUSE_S]
    speaking_time = max(span - sum(pauses), 1e-3)
    runs, current = [], 1
    for g in gaps:
        if g >= PAUSE_S:
            runs.append(current)
            current = 1
        else:
            current += 1
    runs.append(current)
    normed = [norm_word(w.text) for w in spoken]
    repetitions = sum(1 for a, b in zip(normed, normed[1:], strict=False) if a == b)
    repetitions += sum(
        1 for i in range(len(normed) - 3) if normed[i : i + 2] == normed[i + 2 : i + 4]
    )
    fillers = sum(1 for w in normed if w in FILLERS)
    n = len(spoken)
    return {
        "words": float(n),
        "speaking_span_s": span,
        "speech_rate_wpm": n / span * 60.0,
        "articulation_rate_wps": n / speaking_time,
        "pause_count": float(len(pauses)),
        "pauses_per_minute": len(pauses) / span * 60.0,
        "mean_pause_s": sum(pauses) / len(pauses) if pauses else 0.0,
        "long_pauses": float(sum(1 for p in pauses if p >= LONG_PAUSE_S)),
        "pause_time_ratio": sum(pauses) / span,
        "mean_length_of_run": sum(runs) / len(runs),
        "repetitions": float(repetitions),
        "filled_pauses": float(fillers),
    }


def fluency_value(measures: dict[str, float], fmap: dict[str, Any] | None = None) -> float | None:
    """Apply the fitted logistic map; ``None`` if the map is unfitted."""
    fmap = fmap or FLUENCY_MAP
    feats = fmap.get("features") or {}
    if not feats:
        return None
    z = float(fmap["intercept"])
    for name, spec in feats.items():
        x = measures.get(name)
        if x is None:
            return None
        z += float(spec["coef"]) * (x - float(spec["mean"])) / max(float(spec["sd"]), 1e-9)
    return _sigmoid(z)


def _fluency_feedback(words: list[Word]) -> list[dict[str, Any]]:
    out = []
    spoken = [w for w in words if norm_word(w.text)]
    for a, b in zip(spoken, spoken[1:], strict=False):
        gap = b.start - a.end
        if gap >= LONG_PAUSE_S:
            out.append(
                {
                    "type": "long_pause",
                    "start": round(a.end, 2),
                    "end": round(b.start, 2),
                    "message": f"a {gap:.1f}s pause before '{b.text}'",
                }
            )
        if norm_word(a.text) == norm_word(b.text):
            out.append(
                {
                    "type": "repetition",
                    "start": round(a.start, 2),
                    "end": round(b.end, 2),
                    "message": f"'{b.text}' was repeated",
                }
            )
    return out[:8]


def assess_fluency(
    transcript: Transcript,
    *,
    language_code: str | None,
    quality_issues: list[str],
    task_type: str = "free_speech",
) -> DimensionResult:
    words = transcript.words
    if "no_speech_detected" in quality_issues:
        return DimensionResult("fluency", Status.ABSTAINED, "timing", reason="no speech detected")
    if not words or any(w.start is None for w in words):
        return DimensionResult(
            "fluency", Status.ABSTAINED, "timing", reason="no word timing from the recogniser"
        )
    measures = fluency_measures(words)
    if not measures or measures["words"] < MIN_WORDS_FOR_FLUENCY:
        return DimensionResult(
            "fluency",
            Status.ABSTAINED,
            "timing",
            measures=measures,
            reason=f"fewer than {MIN_WORDS_FOR_FLUENCY} words: too little speech to judge fluency",
        )
    conf = transcript.confidence or 0.0
    if conf < MIN_TRANSCRIPT_CONFIDENCE:
        return DimensionResult(
            "fluency",
            Status.ABSTAINED,
            "timing",
            measures=measures,
            reason=f"transcript confidence {conf:.2f} too low: word timing is unreliable",
        )
    value = fluency_value(measures)
    validated = (language_code or "", task_type) in FLUENCY_VALIDATED
    if value is None or not validated:
        return DimensionResult(
            "fluency",
            Status.PARTIAL,
            "timing",
            measures=measures,
            reason=(
                "measures only: no fitted fluency map"
                if value is None
                else "measures only: the fluency map is validated for English read-aloud only"
            ),
            feedback=_fluency_feedback(words),
        )
    cap = VALIDATED_CONFIDENCE * (0.5 if "noisy" in quality_issues else 1.0)
    return DimensionResult(
        "fluency",
        Status.OK,
        "timing",
        value=value,
        confidence=cap,
        measures=measures,
        feedback=_fluency_feedback(words),
    )


# --- intelligibility / pronunciation ---------------------------------------------


def align_target(target: str, words: list[Word]) -> list[dict[str, Any]]:
    """Align target words with recognised words (word-level, deterministic).

    Each target word becomes ``{target, heard, start, end, probability,
    recognised}``. ``recognised`` means an exact match after normalization.
    Accents/diacritics are normalized away, so a word heard with or without
    an accent mark counts the same.
    """
    target_tokens = tokens(target)
    heard = [(norm_word(w.text), w) for w in words if norm_word(w.text)]
    matcher = SequenceMatcher(None, target_tokens, [h for h, _ in heard], autojunk=False)
    out: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for k in range(i2 - i1):
            t = target_tokens[i1 + k]
            j = j1 + k if tag in ("equal", "replace") and j1 + k < j2 else None
            w = heard[j][1] if j is not None else None
            out.append(
                {
                    "target": t,
                    "heard": heard[j][0] if j is not None else "",
                    "start": None if w is None else round(w.start, 2),
                    "end": None if w is None else round(w.end, 2),
                    "probability": None if w is None else w.probability,
                    "recognised": tag == "equal",
                }
            )
    return out


def assess_intelligibility(
    transcript: Transcript,
    task: SpeakingTask,
    *,
    quality_issues: list[str],
    language_code: str | None = None,
) -> DimensionResult:
    if task.task_type != "read_aloud" or not task.target_text:
        return DimensionResult(
            "intelligibility",
            Status.ABSTAINED,
            "transcript",
            reason="needs a read-aloud task with a target text",
        )
    if "no_speech_detected" in quality_issues:
        return DimensionResult(
            "intelligibility", Status.ABSTAINED, "transcript", reason="no speech detected"
        )
    if "noisy" in quality_issues:
        return DimensionResult(
            "intelligibility",
            Status.ABSTAINED,
            "transcript",
            reason="background noise: recogniser errors cannot be separated from the speaker's",
        )
    conf = transcript.confidence or 0.0
    alignment = align_target(task.target_text, transcript.words)
    if not alignment:
        return DimensionResult(
            "intelligibility", Status.ABSTAINED, "transcript", reason="empty target text"
        )
    recognised = sum(1 for a in alignment if a["recognised"])
    value = recognised / len(alignment)
    if conf < MIN_TRANSCRIPT_CONFIDENCE and value < 1.0:
        return DimensionResult(
            "intelligibility",
            Status.ABSTAINED,
            "transcript",
            measures={"recognised_ratio": value, "transcript_confidence": conf},
            reason="low transcript confidence: unrecognised words may be recogniser errors",
        )
    # No word-level corrections: most words the recogniser misses were
    # pronounced acceptably (see the module docstring), so naming them
    # would mostly be false corrections, and more so for some accents.
    feedback = (
        [
            {
                "type": "recogniser_note",
                "message": (
                    f"the speech recogniser picked up {recognised} of {len(alignment)} words. "
                    "Missed words are often a recogniser limit (accent, voice, microphone), "
                    "not a pronunciation error"
                ),
            }
        ]
        if recognised < len(alignment)
        else []
    )
    return DimensionResult(
        "intelligibility",
        Status.OK,
        "transcript",
        value=value,
        confidence=(
            INTELLIGIBILITY_CONFIDENCE if language_code == "en" else UNVALIDATED_CONFIDENCE
        ),
        measures={
            "target_words": len(alignment),
            "recognised": recognised,
            "recognised_ratio": value,
            "transcript_confidence": conf,
        },
        feedback=feedback,
    )


def assess_pronunciation(
    transcript: Transcript, task: SpeakingTask, *, language_code: str | None
) -> DimensionResult:
    if language_code not in PRONUNCIATION_VALIDATED:
        return DimensionResult(
            "pronunciation",
            Status.ABSTAINED,
            "acoustic_proxy",
            reason=(
                "no pronunciation model validated against expert ratings for this language; "
                "intelligibility is reported instead"
            ),
        )
    if task.task_type != "read_aloud" or not task.target_text:
        return DimensionResult(
            "pronunciation", Status.ABSTAINED, "acoustic_proxy", reason="needs a target text"
        )
    alignment = align_target(task.target_text, transcript.words)
    probs = [a["probability"] if a["recognised"] else 0.0 for a in alignment]
    if not probs:
        return DimensionResult(
            "pronunciation", Status.ABSTAINED, "acoustic_proxy", reason="empty target"
        )
    value = sum(p or 0.0 for p in probs) / len(probs)
    weakest = sorted(
        (a for a in alignment if a["recognised"]), key=lambda a: a["probability"] or 0.0
    )[:3]
    return DimensionResult(
        "pronunciation",
        Status.OK,
        "acoustic_proxy",
        value=value,
        confidence=0.4,
        measures={"mean_word_probability": value},
        reason="word-level recogniser certainty; not a phoneme-level analysis",
        feedback=[
            {
                "type": "least_certain",
                "word": a["target"],
                "start": a["start"],
                "end": a["end"],
                "message": f"the recogniser was least sure about '{a['target']}'",
            }
            for a in weakest
        ],
    )


def assess_speaking(
    transcript: Transcript,
    task: SpeakingTask,
    *,
    language_code: str | None,
    quality_issues: list[str],
) -> list[DimensionResult]:
    return [
        assess_fluency(
            transcript,
            language_code=language_code,
            quality_issues=quality_issues,
            task_type=task.task_type,
        ),
        assess_intelligibility(
            transcript, task, quality_issues=quality_issues, language_code=language_code
        ),
        assess_pronunciation(transcript, task, language_code=language_code),
    ]
