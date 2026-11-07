"""Score raw model responses against labeled cases (pure; no model calls).

Scoring reuses the **production** code paths, so it measures what a learner
would actually get:

- the grammar response is parsed with :func:`src.llm.schemas.parse_structured`
  into ``GrammarAnalysis`` (exactly what ``generate_structured`` does), then
  filtered by the production policy ``src.agents.grammar._select_errors``;
- the surfaced errors run through the production evidence pipeline
  (:func:`src.evidence.build_events`), which is what reaches the learner model;
- the vocabulary response is parsed with the agent's own
  ``_parse_vocabulary_response``.

Alongside, a structural inspection of the raw JSON measures what the
production parser hides (it fills a missing ``classification`` with "wrong"
and a missing ``confidence`` with 1.0).

Matching rules (documented in ``docs/real-model-evaluation.md``):

- a surfaced error *localizes* an expected error when their normalized spans
  overlap (one contains the other, or token Jaccard >= 0.5);
- a correction is right when an accepted correction occurs in the model's
  normalized correction (or vice versa);
- a construction is right when its normalized id equals, contains, or is
  contained in an accepted id.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from evals.real.schema import GrammarCase, VocabularyCase
from src.llm.schemas import (
    ERROR_CLASSIFICATIONS,
    GRAMMAR_CLASSIFICATIONS,
    GrammarAnalysis,
    parse_structured,
    strip_code_fences,
)

#: Fields the grammar prompt asks for in every entry.
GRAMMAR_REQUIRED_FIELDS = (
    "original",
    "correction",
    "construction",
    "classification",
    "severity",
    "confidence",
)
SEVERITIES = ("minor", "moderate", "critical")
VOCAB_REQUIRED_FIELDS = ("word", "translation", "pos", "context_sentence")

_PUNCT = re.compile(r"[^\w\s']+", re.UNICODE)
_ARTICLES = {
    "el", "la", "los", "las", "un", "una", "il", "lo", "gli", "le", "l'",
    "der", "die", "das", "ein", "eine", "the", "a", "an", "to",
}  # fmt: skip


def norm(text: str | None) -> str:
    """Casefold, unify quotes, strip punctuation and extra whitespace."""
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text).casefold().replace("’", "'")
    t = _PUNCT.sub(" ", t)
    return " ".join(t.split())


def norm_word(text: str | None) -> str:
    """:func:`norm` plus leading-article removal (for word and gloss matching)."""
    tokens = norm(text).split()
    while tokens and tokens[0] in _ARTICLES:
        tokens = tokens[1:]
    return " ".join(tokens)


def norm_construction(text: str | None) -> str:
    from src.evidence.normalizer import normalize_rule

    return normalize_rule(text or "")


def spans_overlap(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    return len(ta & tb) / len(ta | tb) >= 0.5


def correction_matches(model_correction: str, accepted: list[str]) -> bool:
    m = norm(model_correction)
    if not m:
        return False
    return any((n := norm(a)) and (n in m or (len(m) >= 3 and m in n)) for a in accepted)


def construction_matches(model_construction: str, accepted: list[str]) -> bool:
    m = norm_construction(model_construction)
    if m in ("", "unknown"):
        return False
    for a in accepted:
        n = norm_construction(a)
        if m == n or n in m or m in n:
            return True
    return False


# --------------------------------------------------------------------------- #
# Structured-output inspection
# --------------------------------------------------------------------------- #


@dataclass
class StructureReport:
    """What the raw response looked like, before production parsing."""

    json_valid: bool = False
    #: "object_with_list" | "bare_list" | "object_other" | "scalar" | "invalid"
    top_level: str = "invalid"
    schema_valid: bool = False
    entries: list[dict[str, Any]] = field(default_factory=list)
    entries_missing_field: int = 0
    entries_invalid_field: int = 0
    entries_unsupported_assessment: int = 0
    missing_by_field: dict[str, int] = field(default_factory=dict)
    #: The production parser failed but the payload was a recoverable list.
    recoverable: bool = False


def inspect_grammar_json(text: str | None) -> StructureReport:
    rep = StructureReport()
    if not text:
        return rep
    try:
        data = json.loads(strip_code_fences(text))
    except (json.JSONDecodeError, TypeError):
        return rep
    rep.json_valid = True
    entries: list[Any]
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        rep.top_level, entries = "object_with_list", data["errors"]
    elif isinstance(data, list):
        rep.top_level, entries = "bare_list", data
    elif isinstance(data, dict):
        rep.top_level, entries = "object_other", []
    else:
        rep.top_level, entries = "scalar", []
    rep.schema_valid = parse_structured(text, GrammarAnalysis) is not None
    rep.entries = [e for e in entries if isinstance(e, dict)]
    for entry in rep.entries:
        missing = [f for f in GRAMMAR_REQUIRED_FIELDS if f not in entry]
        for f in missing:
            rep.missing_by_field[f] = rep.missing_by_field.get(f, 0) + 1
        rep.entries_missing_field += int(bool(missing))
        invalid = False
        cls = entry.get("classification")
        if cls is not None and str(cls).lower() not in GRAMMAR_CLASSIFICATIONS:
            invalid = True
            rep.entries_unsupported_assessment += 1
        sev = entry.get("severity")
        if sev is not None and str(sev).lower() not in SEVERITIES:
            invalid = True
        conf = entry.get("confidence")
        if conf is not None and not (isinstance(conf, (int, float)) and 0.0 <= float(conf) <= 1.0):
            invalid = True
        rep.entries_invalid_field += int(invalid)
    if not rep.schema_valid and rep.top_level == "bare_list":
        rep.recoverable = (
            parse_structured(json.dumps({"errors": rep.entries}), GrammarAnalysis) is not None
        )
    return rep


# --------------------------------------------------------------------------- #
# Grammar outcomes
# --------------------------------------------------------------------------- #


@dataclass
class Candidate:
    """One deviation the model proposed (before the production policy)."""

    original: str
    classification: str
    raw_confidence: float | None
    pipeline_confidence: float
    is_error_class: bool
    surfaced: bool
    matched_expected: int | None  # index into case.expected_errors
    correction_ok: bool
    construction_ok: bool


@dataclass
class GrammarOutcome:
    case_id: str
    provider_key: str
    prompt: str
    repeat: int
    ok: bool  # the call itself succeeded
    error_category: str | None
    structure: StructureReport
    candidates: list[Candidate]
    predicted_error: bool
    #: Case-level correctness of the *detection decision* (None for ambiguous).
    detection_correct: bool | None
    #: Error cases only: was at least one expected error localized?
    localized: bool | None
    expected_matched: int
    expected_total: int
    spurious_surfaced: int  # surfaced errors matching no expected error
    reported_acceptable_class: bool  # a non-error entry used an accepted class
    evidence: dict[str, Any]
    latency_ms: float
    input_tokens: int
    output_tokens: int
    tokens_estimated: bool
    cost_usd: float


def _evidence_for(case: GrammarCase, surfaced: list[dict[str, Any]]) -> dict[str, Any]:
    """Run surfaced errors through the production evidence pipeline and grade it."""
    from src.evidence import build_events
    from src.evidence.difficulty import difficulty_to_cefr
    from src.evidence.events import EventType

    state = {
        "user_id": "eval",
        "language": case.language,
        "session_id": f"eval-{case.case_id}",
        "mode": "conversation",
        "messages": [{"role": "user", "content": case.text}],
        "grammar_errors": surfaced,
        "new_vocabulary": [],
    }
    events = [e for e in build_events(state) if e.event_type == EventType.GRAMMAR_ERROR]
    graded = []
    for ev in events:
        idx = next(
            (
                i
                for i, exp in enumerate(case.expected_errors)
                if spans_overlap(ev.observed or "", exp.span)
            ),
            None,
        )
        exp = case.expected_errors[idx] if idx is not None else None
        graded.append(
            {
                "matched": idx is not None,
                "skill_ok": None if exp is None else ev.skill == exp.skill,
                "expected_skill": None if exp is None else exp.skill,
                "subskill_ok": None
                if exp is None
                else construction_matches(ev.subskill or "", exp.constructions),
                "difficulty_known": ev.difficulty is not None,
                "difficulty_ok": None
                if exp is None or exp.construction_cefr is None or ev.difficulty is None
                else difficulty_to_cefr(ev.difficulty) == exp.construction_cefr,
            }
        )
    keys = [(norm(e.observed), e.item_id) for e in events]
    return {
        "events": len(events),
        "graded": graded,
        "duplicate_events": len(keys) - len(set(keys)),
        "distinct_expected_hit": len(
            {
                i
                for ev in events
                for i, exp in enumerate(case.expected_errors)
                if spans_overlap(ev.observed or "", exp.span)
            }
        ),
    }


def score_grammar(case: GrammarCase, record: dict[str, Any]) -> GrammarOutcome:
    """Score one grammar response for one case."""
    from src.agents.grammar import _select_errors

    text = record.get("response_text")
    structure = inspect_grammar_json(text)
    analysis = parse_structured(text, GrammarAnalysis) if text else None
    surfaced = _select_errors(analysis)
    surfaced_originals = [s["original"] for s in surfaced]

    candidates: list[Candidate] = []
    if analysis is not None:
        raw_entries = structure.entries if structure.top_level == "object_with_list" else []
        for i, e in enumerate(analysis.errors):
            raw = raw_entries[i] if i < len(raw_entries) else {}
            raw_conf = raw.get("confidence")
            idx = next(
                (
                    j
                    for j, exp in enumerate(case.expected_errors)
                    if spans_overlap(e.original, exp.span)
                ),
                None,
            )
            exp = case.expected_errors[idx] if idx is not None else None
            candidates.append(
                Candidate(
                    original=e.original,
                    classification=e.classification.lower(),
                    raw_confidence=float(raw_conf) if isinstance(raw_conf, (int, float)) else None,
                    pipeline_confidence=e.confidence,
                    is_error_class=e.classification.lower() in ERROR_CLASSIFICATIONS,
                    surfaced=e.original in surfaced_originals and e.is_error(),
                    matched_expected=idx,
                    correction_ok=exp is not None
                    and correction_matches(e.correction, exp.corrections),
                    construction_ok=exp is not None
                    and construction_matches(e.construction or e.rule, exp.constructions),
                )
            )

    predicted = bool(surfaced)
    matched = {
        c.matched_expected for c in candidates if c.surfaced and c.matched_expected is not None
    }
    if case.has_error is None:
        detection: bool | None = None
    else:
        detection = predicted == case.has_error
    return GrammarOutcome(
        case_id=case.case_id,
        provider_key=f"{record['provider']}:{record['model']}",
        prompt=record["prompt"],
        repeat=int(record.get("repeat", 0)),
        ok=bool(record.get("ok")),
        error_category=record.get("error_category"),
        structure=structure,
        candidates=candidates,
        predicted_error=predicted,
        detection_correct=detection,
        localized=(len(matched) > 0) if case.has_error else None,
        expected_matched=len(matched),
        expected_total=len(case.expected_errors),
        spurious_surfaced=sum(1 for c in candidates if c.surfaced and c.matched_expected is None),
        reported_acceptable_class=any(
            not c.is_error_class and c.classification in case.acceptable_classifications
            for c in candidates
        ),
        evidence=_evidence_for(case, [dict(e) for e in surfaced]),
        latency_ms=float(record.get("latency_ms") or 0.0),
        input_tokens=int(record.get("input_tokens") or 0),
        output_tokens=int(record.get("output_tokens") or 0),
        tokens_estimated=bool(record.get("tokens_estimated", True)),
        cost_usd=float(record.get("cost_usd") or 0.0),
    )


# --------------------------------------------------------------------------- #
# Vocabulary outcomes
# --------------------------------------------------------------------------- #


@dataclass
class VocabularyOutcome:
    case_id: str
    provider_key: str
    repeat: int
    ok: bool
    error_category: str | None
    json_valid: bool
    schema_valid: bool  # top-level {"words": [...]} with dict entries
    entries: int
    entries_missing_field: int
    extracted: list[str]
    required_total: int
    required_found: int
    relevant_extracted: int  # extracted words that are required or optional
    forbidden_extracted: int
    translations_checked: int
    translations_ok: int
    produced_checked: int
    produced_ok: int
    latency_ms: float
    input_tokens: int
    output_tokens: int
    tokens_estimated: bool
    cost_usd: float


def _gloss_ok(predicted: str, accepted: list[str]) -> bool:
    p = norm_word(predicted)
    if not p:
        return False
    for a in accepted:
        n = norm_word(a)
        if (
            p == n
            or re.search(rf"\b{re.escape(n)}\b", p)
            or (len(p) >= 4 and re.search(rf"\b{re.escape(p)}\b", n))
        ):
            return True
    return False


def score_vocabulary(case: VocabularyCase, record: dict[str, Any]) -> VocabularyOutcome:
    from src.agents.vocabulary import _parse_vocabulary_response
    from src.evidence.events import EventType
    from src.evidence.extractor import extract_vocabulary_events
    from src.evidence.provenance import Provenance

    text = record.get("response_text") or ""
    json_valid = schema_valid = False
    entries: list[dict[str, Any]] = []
    try:
        data = json.loads(strip_code_fences(text))
        json_valid = True
        if isinstance(data, dict) and isinstance(data.get("words"), list):
            entries = [w for w in data["words"] if isinstance(w, dict)]
            schema_valid = len(entries) == len(data["words"])
    except (json.JSONDecodeError, TypeError):
        pass
    items = _parse_vocabulary_response(text) if text else []
    extracted = [norm_word(i["word"]) for i in items]

    def forms(w: Any) -> set[str]:
        return {norm_word(w.word), *(norm_word(f) for f in w.forms)}

    relevant = {norm_word(o) for o in case.optional_words}
    for w in case.required_words:
        relevant |= forms(w)
    forbidden = {norm_word(f) for f in case.forbidden_words}

    found = [w for w in case.required_words if forms(w) & set(extracted)]
    tr_checked = tr_ok = 0
    for w in found:
        item = next(i for i in items if norm_word(i["word"]) in forms(w))
        tr_checked += 1
        tr_ok += int(_gloss_ok(item.get("translation", ""), w.translations))

    events = extract_vocabulary_events(
        "eval",
        case.language,
        [dict(i) for i in items],
        provenance=Provenance("eval"),
        messages=[{"role": "user", "content": case.user_text}],
    )
    by_word = {norm_word(e.item_id): e for e in events}
    prod_checked = prod_ok = 0
    for w in found:
        ev = next((by_word[f] for f in forms(w) if f in by_word), None)
        if ev is None:
            continue
        prod_checked += 1
        is_produced = ev.event_type == EventType.VOCAB_PRODUCED
        prod_ok += int(is_produced == w.produced_by_learner)

    return VocabularyOutcome(
        case_id=case.case_id,
        provider_key=f"{record['provider']}:{record['model']}",
        repeat=int(record.get("repeat", 0)),
        ok=bool(record.get("ok")),
        error_category=record.get("error_category"),
        json_valid=json_valid,
        schema_valid=schema_valid,
        entries=len(entries),
        entries_missing_field=sum(
            1 for e in entries if any(f not in e for f in VOCAB_REQUIRED_FIELDS)
        ),
        extracted=extracted,
        required_total=len(case.required_words),
        required_found=len(found),
        relevant_extracted=sum(1 for x in extracted if x in relevant),
        forbidden_extracted=sum(1 for x in extracted if x in forbidden),
        translations_checked=tr_checked,
        translations_ok=tr_ok,
        produced_checked=prod_checked,
        produced_ok=prod_ok,
        latency_ms=float(record.get("latency_ms") or 0.0),
        input_tokens=int(record.get("input_tokens") or 0),
        output_tokens=int(record.get("output_tokens") or 0),
        tokens_estimated=bool(record.get("tokens_estimated", True)),
        cost_usd=float(record.get("cost_usd") or 0.0),
    )
