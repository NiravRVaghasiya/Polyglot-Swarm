"""Evidence-driven mastery estimation (``lkm-evidence-v2``, ADR-0031).

A pure function from a learner's *active* evidence set (see
:func:`src.evidence.store.active_events`) to one :class:`SkillEstimate` per
skill. Nothing here does I/O, reads the clock, or depends on input order, so
the same evidence always produces the same estimate (deterministic replay).

Model
-----
Each skill has a latent ability ``theta`` on a logit scale. A graded
observation ``i`` with outcome ``y_i`` in [0, 1] on a task of difficulty
``b_i`` has success probability ``sigmoid(theta - b_i)`` (a Rasch-style model).
``theta`` is the weighted maximum-a-posteriori estimate under a weak
``Normal(0, prior_sd**2)`` prior. Reported ``mastery`` is ``sigmoid(theta)``: the
model's success probability on a *reference* task of difficulty 0.5 (about the
B1/B2 boundary). Its standard error comes from the observed Fisher information.

Weights. Each observation's weight is the product of:

- **reliability**: the evaluator's ``confidence`` in its own judgment;
- **recency**: ``0.5 ** (age / half_life)`` with a floor, where age is measured
  from the newest evidence *for the same skill* (not the wall clock, which would
  make replay time-dependent, and not other skills' evidence, which would
  couple skills that are meant to be estimated independently);
- **repetition**: the k-th most recent observation of the *same item* is
  weighted ``repetition_ratio ** k``, so drilling one item cannot stand in for
  breadth;
- **difficulty information**: observations with unknown difficulty are
  discounted, and placed at the reference difficulty.

Independence. Exact duplicates (equal fingerprints) and correlated judgments
(the same ``correlation_id`` and item, e.g. two agents grading one sentence)
are merged into one observation before weighting: their outcomes are averaged
by reliability and the merged observation keeps the *maximum* reliability, not
the sum.

Exposure. Practice without a graded outcome (turns, words met in the tutor's
reply, ``abstain`` judgments) counts toward coverage but never toward mastery.

What the numbers are not. ``uncertainty`` is ``SE / prior_sd`` (1.0 = no
information beyond the prior). The interval is an approximate 95% interval
*under the model's assumptions*. ``evidence_index`` is an ordinal
evidence-sufficiency score. None of them is a calibrated probability: there is
no ground-truth proficiency data in the system to calibrate against.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from src.learner.cefr_bands import mastery_to_cefr
from src.learner.mastery_engine import MasteryEngine, SkillBelief
from src.util import parse_timestamp as _parse_time
from src.util import sigmoid as _sigmoid

#: Method tag stored with every materialized estimate and history row.
METHOD = "lkm-evidence-v2"


class EvidenceStatus(StrEnum):
    """How much a skill estimate can be relied on (ordered weakest first)."""

    INSUFFICIENT = "insufficient_evidence"
    PROVISIONAL = "provisional"
    ESTIMATED = "estimated"
    VALIDATED = "validated"


STATUS_ORDER: list[EvidenceStatus] = [
    EvidenceStatus.INSUFFICIENT,
    EvidenceStatus.PROVISIONAL,
    EvidenceStatus.ESTIMATED,
    EvidenceStatus.VALIDATED,
]


def status_rank(status: str) -> int:
    """Ordinal of a status (insufficient_evidence=0 .. validated=3)."""
    return STATUS_ORDER.index(EvidenceStatus(status))


@dataclass(frozen=True)
class EngineConfig:
    """Every tunable assumption of the engine, in one documented place."""

    #: Prior SD of ability (logits). Weak: three or four confident graded
    #: observations dominate it.
    prior_sd: float = 1.5
    #: Difficulty 0..1 maps to logits ``scale * (d - 0.5)``, i.e. -2..+2.
    difficulty_scale: float = 4.0
    #: Weight multiplier when the task difficulty is unknown.
    unknown_difficulty_discount: float = 0.8
    #: Weight ratio between consecutive (newest-first) repeats of one item.
    repetition_ratio: float = 0.5
    #: Recency half-life in days, and the floor old evidence decays to.
    recency_half_life_days: float = 60.0
    recency_floor: float = 0.25
    #: z for the reported interval.
    interval_z: float = 1.96
    #: Status thresholds (independent observations / distinct items / sessions).
    provisional_min_independent: int = 3
    provisional_min_items: int = 2
    estimated_min_independent: int = 8
    estimated_min_items: int = 4
    estimated_min_sessions: int = 2
    estimated_max_interval_width: float = 0.4
    validated_min_observations: int = 2
    #: Saturation constant of the evidence index.
    evidence_index_k: float = 6.0
    #: Item-level outcome needed to call an item "demonstrated" / "struggling".
    demonstrated_threshold: float = 0.7
    struggling_threshold: float = 0.35

    def digest(self) -> str:
        """A short hash of the config, part of every evidence digest."""
        blob = repr(sorted(asdict(self).items()))
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


DEFAULT_CONFIG = EngineConfig()

# Graded assessments -> outcome in [0, 1].
_GRADED_SIGNAL: dict[str, float] = {
    "correct": 1.0,
    "incorrect": 0.0,
    "awkward": 0.35,  # non-idiomatic but understood
    "observed": 0.75,  # the learner produced the item (untested for accuracy)
    "produced": 0.75,
}
#: Acceptable variation (not a learner gap): a mild positive outcome.
_NEUTRAL_ASSESSMENTS = frozenset({"regional", "informal", "formal", "unusual", "acceptable"})
#: Assessments that carry no graded outcome: practice/exposure only.
_EXPOSURE_ASSESSMENTS = frozenset({"exposed", "abstain"})
#: Event types that are practice/exposure regardless of assessment.
_EXPOSURE_EVENT_TYPES = frozenset({"TURN_COMPLETED", "VOCAB_OBSERVED"})
#: Task types whose results come from a validated instrument. No producer in
#: the app emits these yet, so in practice no skill reaches ``validated``.
VALIDATED_TASK_TYPES = frozenset({"standardized_test", "expert_rating"})


@dataclass(frozen=True)
class Observation:
    """One evidence row, normalized for the engine."""

    event_id: str
    skill: str
    kind: str  # "graded" | "exposure" | "ignored"
    signal: float | None
    reliability: float
    item_key: str
    group_key: str
    fingerprint: str
    subskill: str | None
    objective_id: str | None
    session_id: str | None
    task_type: str | None
    difficulty: float | None
    difficulty_basis: str
    created_at: str
    timestamp: float | None  # POSIX seconds, None if unparseable


def _classify(row: dict[str, Any]) -> tuple[str, float | None]:
    event_type = str(row.get("event_type") or "")
    assessment = (row.get("assessment") or "").lower() or None
    if event_type in _EXPOSURE_EVENT_TYPES:
        return "exposure", None
    if assessment is None:
        return "ignored", None
    if assessment in _EXPOSURE_ASSESSMENTS:
        return "exposure", None
    if assessment in _NEUTRAL_ASSESSMENTS:
        return "graded", 0.6
    if assessment == "scored":
        # A continuous score in [0, 1] (ADR-0034, e.g. fluency); without a
        # usable score the row carries no graded outcome.
        payload = row.get("payload")
        score = payload.get("score") if isinstance(payload, dict) else None
        if isinstance(score, (int, float)) and 0.0 <= float(score) <= 1.0:
            return "graded", float(score)
        return "ignored", None
    signal = _GRADED_SIGNAL.get(assessment)
    if signal is None:
        return "ignored", None
    return "graded", signal


def _reliability(row: dict[str, Any]) -> float:
    """Evaluator confidence, discounted by transcription confidence when the
    evidence was derived from a machine transcript (ADR-0034).

    The two are stored separately; only here are they combined, so a poor
    recording lowers how much an observation counts without ever being read
    as poor learner performance.
    """
    conf = max(0.0, min(1.0, float(row.get("confidence", 1.0) or 0.0)))
    tc = row.get("transcription_confidence")
    if isinstance(tc, (int, float)):
        conf *= max(0.0, min(1.0, float(tc)))
    return conf


def to_observation(row: dict[str, Any]) -> Observation | None:
    """Normalize one evidence row; ``None`` if it concerns no skill."""
    skill = row.get("skill")
    if not skill:
        return None
    from src.evidence.events import evidence_fingerprint

    kind, signal = _classify(row)
    fingerprint = str(row.get("fingerprint") or evidence_fingerprint(row))
    item = row.get("item_id") or row.get("objective_id")
    item_key = f"{skill}:{str(item).strip().lower()}" if item else f"{skill}:#{fingerprint}"
    correlation = row.get("correlation_id")
    group_key = f"c:{correlation}|{item_key}" if correlation else f"f:{fingerprint}"
    raw_difficulty = row.get("difficulty")
    difficulty = None if raw_difficulty is None else max(0.0, min(1.0, float(raw_difficulty)))
    basis = str(row.get("difficulty_basis") or "unknown")
    if difficulty is None:
        basis = "unknown"
    return Observation(
        event_id=str(row.get("event_id") or fingerprint),
        skill=str(skill),
        kind=kind,
        signal=signal,
        reliability=_reliability(row),
        item_key=item_key,
        group_key=group_key,
        fingerprint=fingerprint,
        subskill=row.get("subskill"),
        objective_id=row.get("objective_id"),
        session_id=row.get("session_id"),
        task_type=row.get("task_type"),
        difficulty=difficulty,
        difficulty_basis=basis,
        created_at=str(row.get("created_at") or ""),
        timestamp=_parse_time(row.get("created_at")),
    )


@dataclass
class Contribution:
    """How one evidence event entered (or did not enter) a skill estimate."""

    event_id: str
    role: str  # counted | merged | exposure | ignored
    group_key: str
    item_key: str
    signal: float | None = None
    reliability: float = 0.0
    recency: float = 1.0
    repetition: float = 1.0
    difficulty_factor: float = 1.0
    difficulty_logit: float = 0.0
    weight: float = 0.0
    merged_into: str | None = None


@dataclass
class EvidenceQuality:
    """Quality of the graded evidence behind an estimate (each in [0, 1])."""

    mean_reliability: float = 0.0
    known_difficulty_share: float = 0.0
    #: Share of graded events merged away as duplicates/correlated judgments.
    redundancy_share: float = 0.0
    #: Share of the skill's events that were exposure-only.
    exposure_share: float = 0.0

    def score(self) -> float:
        """One quality number: reliability, nudged up by known difficulty."""
        return round(self.mean_reliability * (0.8 + 0.2 * self.known_difficulty_share), 4)


@dataclass
class SkillCoverage:
    """What has been practised vs assessed vs demonstrated for one skill."""

    practice_events: int = 0
    practiced_items: int = 0
    assessed_items: int = 0
    assessed_objectives: int = 0
    assessed_subskills: int = 0
    demonstrated_items: int = 0
    demonstrated_objectives: int = 0
    struggling_items: int = 0
    #: Catalog-relative coverage (only where a catalog of objectives exists,
    #: e.g. grammar constructions from the language pack).
    catalog_size: int | None = None
    catalog_assessed: int | None = None
    catalog_demonstrated: int | None = None
    unassessed_objectives: list[str] = field(default_factory=list)
    demonstrated_objective_ids: list[str] = field(default_factory=list)
    struggling_objective_ids: list[str] = field(default_factory=list)

    def catalog_assessed_fraction(self) -> float | None:
        if not self.catalog_size:
            return None
        return round((self.catalog_assessed or 0) / self.catalog_size, 4)


@dataclass
class SkillEstimate:
    """The model's evidence-backed view of one skill.

    ``mastery`` is ``None`` when there is no graded evidence: missing evidence
    is never read as zero mastery. ``cefr`` is ``None`` below ``provisional``.
    """

    skill: str
    method: str = METHOD
    status: str = EvidenceStatus.INSUFFICIENT.value
    mastery: float | None = None
    mastery_low: float | None = None
    mastery_high: float | None = None
    ability: float | None = None
    ability_se: float | None = None
    uncertainty: float = 1.0
    evidence_index: float = 0.0
    cefr: str | None = None
    raw_count: int = 0
    graded_count: int = 0
    independent_count: int = 0
    effective_n: float = 0.0
    distinct_items: int = 0
    distinct_objectives: int = 0
    sessions: int = 0
    validated_observations: int = 0
    quality: EvidenceQuality = field(default_factory=EvidenceQuality)
    coverage: SkillCoverage = field(default_factory=SkillCoverage)
    baseline_mastery: float | None = None
    last_evidence_at: str | None = None
    evidence_digest: str = ""
    event_ids: list[str] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)

    @property
    def interval_width(self) -> float:
        if self.mastery_low is None or self.mastery_high is None:
            return 1.0
        return self.mastery_high - self.mastery_low

    @property
    def confidence_label(self) -> str:
        """A categorical reading of the evidence (``none``/``low``/``medium``/``high``)."""
        if self.mastery is None:
            return "none"
        rank = status_rank(self.status)
        if rank == 0:
            return "low"
        if rank == 1:
            return "low" if self.interval_width > 0.5 else "medium"
        return "high" if self.interval_width <= 0.25 else "medium"

    def as_dict(self, *, include_contributions: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "skill": self.skill,
            "method": self.method,
            "status": self.status,
            "mastery": _r(self.mastery),
            "mastery_low": _r(self.mastery_low),
            "mastery_high": _r(self.mastery_high),
            "uncertainty": round(self.uncertainty, 4),
            "evidence_index": round(self.evidence_index, 4),
            "confidence_label": self.confidence_label,
            "cefr": self.cefr,
            "evidence": {
                "raw_count": self.raw_count,
                "graded_count": self.graded_count,
                "independent_count": self.independent_count,
                "effective_n": round(self.effective_n, 4),
                "distinct_items": self.distinct_items,
                "distinct_objectives": self.distinct_objectives,
                "sessions": self.sessions,
                "validated_observations": self.validated_observations,
            },
            "quality": {**asdict(self.quality), "score": self.quality.score()},
            "coverage": {
                **asdict(self.coverage),
                "catalog_assessed_fraction": self.coverage.catalog_assessed_fraction(),
            },
            "baseline_mastery": _r(self.baseline_mastery),
            "last_evidence_at": self.last_evidence_at,
            "evidence_digest": self.evidence_digest,
        }
        if include_contributions:
            data["contributions"] = [asdict(c) for c in self.contributions]
        return data

    def to_belief(self) -> SkillBelief:
        """The legacy (mastery, uncertainty, sample_size) view, for old callers."""
        return SkillBelief(
            skill=self.skill,
            mastery=self.mastery if self.mastery is not None else 0.0,
            uncertainty=self.uncertainty,
            sample_size=float(self.graded_count),
        )


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


@dataclass
class _Group:
    key: str
    item_key: str
    members: list[Observation]

    @property
    def lead(self) -> Observation:
        return self.members[0]

    @property
    def reliability(self) -> float:
        return max(m.reliability for m in self.members)

    @property
    def signal(self) -> float:
        total = sum(m.reliability for m in self.members)
        if total <= 0:
            return sum(m.signal or 0.0 for m in self.members) / len(self.members)
        return sum((m.signal or 0.0) * m.reliability for m in self.members) / total

    @property
    def timestamp(self) -> float | None:
        stamps = [m.timestamp for m in self.members if m.timestamp is not None]
        return max(stamps) if stamps else None

    @property
    def difficulty(self) -> float | None:
        known = [m.difficulty for m in self.members if m.difficulty is not None]
        return sum(known) / len(known) if known else None


def fit_ability(data: list[tuple[float, float, float]], *, prior_sd: float) -> tuple[float, float]:
    """Weighted MAP ability for ``(outcome, difficulty_logit, weight)`` triples.

    Newton-Raphson on the concave log-posterior; returns ``(theta, se)``.
    Deterministic and order-independent up to float summation.
    """
    prior_precision = 1.0 / (prior_sd * prior_sd)
    theta = 0.0
    for _ in range(100):
        grad = -theta * prior_precision
        info = prior_precision
        for y, b, w in data:
            p = _sigmoid(theta - b)
            grad += w * (y - p)
            info += w * p * (1.0 - p)
        step = grad / info
        theta += step
        if abs(step) < 1e-10:
            break
    info = prior_precision
    for _y, b, w in data:
        p = _sigmoid(theta - b)
        info += w * p * (1.0 - p)
    return theta, 1.0 / math.sqrt(info)


class EvidenceMasteryEngine:
    """Estimates every skill from a learner's active evidence set."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG

    def estimate_all(
        self,
        rows: list[dict[str, Any]],
        *,
        catalogs: dict[str, list[tuple[str, float | None]]] | None = None,
        with_contributions: bool = False,
    ) -> dict[str, SkillEstimate]:
        """Return one estimate per skill present in ``rows``.

        ``catalogs`` maps a skill to its known objectives as ``(objective_id,
        difficulty)`` pairs, for catalog-relative coverage.
        """
        observations = [o for o in (to_observation(r) for r in rows) if o is not None]
        by_skill: dict[str, list[Observation]] = defaultdict(list)
        for o in observations:
            by_skill[o.skill].append(o)
        baseline_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in sorted(
            rows, key=lambda r: (str(r.get("created_at") or ""), str(r.get("event_id") or ""))
        ):
            if row.get("skill"):
                baseline_rows[str(row["skill"])].append(row)
        return {
            skill: self.estimate_skill(
                skill,
                obs,
                reference_time=max(
                    (o.timestamp for o in obs if o.timestamp is not None), default=None
                ),
                catalog=(catalogs or {}).get(skill),
                baseline_rows=baseline_rows.get(skill, []),
                with_contributions=with_contributions,
            )
            for skill, obs in sorted(by_skill.items())
        }

    def estimate_skill(
        self,
        skill: str,
        observations: list[Observation],
        *,
        reference_time: float | None,
        catalog: list[tuple[str, float | None]] | None = None,
        baseline_rows: list[dict[str, Any]] | None = None,
        with_contributions: bool = False,
    ) -> SkillEstimate:
        cfg = self.config
        observations = sorted(observations, key=lambda o: (o.created_at, o.event_id))
        graded = [o for o in observations if o.kind == "graded"]
        exposure = [o for o in observations if o.kind == "exposure"]
        contributions: list[Contribution] = []

        # 1. Merge duplicates / correlated judgments into independent groups.
        groups: dict[str, _Group] = {}
        for o in graded:
            if o.group_key in groups:
                groups[o.group_key].members.append(o)
            else:
                groups[o.group_key] = _Group(o.group_key, o.item_key, [o])

        # 2. Repetition discount per item, newest first.
        by_item: dict[str, list[_Group]] = defaultdict(list)
        for g in groups.values():
            by_item[g.item_key].append(g)
        repetition: dict[str, float] = {}
        for item_groups in by_item.values():
            ordered = sorted(item_groups, key=lambda g: (g.timestamp or 0.0, g.key), reverse=True)
            for rank, g in enumerate(ordered):
                repetition[g.key] = cfg.repetition_ratio**rank

        # 3. Weights and the ability fit.
        fit_data: list[tuple[float, float, float]] = []
        weights: dict[str, float] = {}
        for g in sorted(groups.values(), key=lambda g: g.key):
            recency = 1.0
            ts = g.timestamp
            if reference_time is not None and ts is not None:
                age_days = max(0.0, (reference_time - ts) / 86400.0)
                recency = max(cfg.recency_floor, 0.5 ** (age_days / cfg.recency_half_life_days))
            difficulty = g.difficulty
            if difficulty is None:
                diff_factor, b = cfg.unknown_difficulty_discount, 0.0
            else:
                diff_factor, b = 1.0, cfg.difficulty_scale * (difficulty - 0.5)
            w = g.reliability * recency * repetition[g.key] * diff_factor
            weights[g.key] = w
            fit_data.append((g.signal, b, w))
            if with_contributions:
                contributions.append(
                    Contribution(
                        event_id=g.lead.event_id,
                        role="counted",
                        group_key=g.key,
                        item_key=g.item_key,
                        signal=round(g.signal, 4),
                        reliability=round(g.reliability, 4),
                        recency=round(recency, 4),
                        repetition=round(repetition[g.key], 4),
                        difficulty_factor=diff_factor,
                        difficulty_logit=round(b, 4),
                        weight=round(w, 6),
                    )
                )
                for m in g.members[1:]:
                    contributions.append(
                        Contribution(
                            event_id=m.event_id,
                            role="merged",
                            group_key=g.key,
                            item_key=g.item_key,
                            signal=m.signal,
                            reliability=m.reliability,
                            merged_into=g.lead.event_id,
                        )
                    )
        if with_contributions:
            for o in exposure:
                contributions.append(Contribution(o.event_id, "exposure", o.group_key, o.item_key))
            for o in observations:
                if o.kind == "ignored":
                    contributions.append(
                        Contribution(o.event_id, "ignored", o.group_key, o.item_key)
                    )

        estimate = SkillEstimate(skill=skill, contributions=contributions)
        estimate.raw_count = len(observations)
        estimate.graded_count = len(graded)
        estimate.independent_count = len(groups)
        estimate.effective_n = sum(weights.values())
        estimate.event_ids = sorted(o.event_id for o in observations)
        estimate.last_evidence_at = max((o.created_at for o in observations), default=None) or None
        estimate.evidence_digest = self._digest(skill, estimate.event_ids)

        graded_items = {g.item_key for g in groups.values()}
        objectives = {o.objective_id for o in graded if o.objective_id}
        sessions = {o.session_id or "(none)" for o in graded}
        estimate.distinct_items = len(graded_items)
        estimate.distinct_objectives = len(objectives)
        estimate.sessions = len(sessions)
        validated_groups = {
            g.key
            for g in groups.values()
            if any(m.task_type in VALIDATED_TASK_TYPES for m in g.members)
        }
        estimate.validated_observations = len(validated_groups)

        estimate.quality = EvidenceQuality(
            mean_reliability=round(sum(g.reliability for g in groups.values()) / len(groups), 4)
            if groups
            else 0.0,
            known_difficulty_share=round(
                sum(1 for g in groups.values() if g.difficulty is not None) / len(groups), 4
            )
            if groups
            else 0.0,
            redundancy_share=round(1.0 - len(groups) / len(graded), 4) if graded else 0.0,
            exposure_share=round(len(exposure) / len(observations), 4) if observations else 0.0,
        )
        estimate.coverage = self._coverage(observations, groups, weights, catalog)
        estimate.baseline_mastery = self._baseline(skill, baseline_rows or [])

        if groups:
            theta, se = fit_ability(fit_data, prior_sd=cfg.prior_sd)
            z = cfg.interval_z
            estimate.ability = theta
            estimate.ability_se = se
            estimate.mastery = _sigmoid(theta)
            estimate.mastery_low = _sigmoid(theta - z * se)
            estimate.mastery_high = _sigmoid(theta + z * se)
            estimate.uncertainty = min(1.0, se / cfg.prior_sd)
            diversity = min(1.0, estimate.distinct_items / cfg.estimated_min_items)
            saturation = estimate.effective_n / (estimate.effective_n + cfg.evidence_index_k)
            estimate.evidence_index = saturation * estimate.quality.mean_reliability * diversity
        estimate.status = self._status(estimate).value
        if status_rank(estimate.status) >= 1 and estimate.mastery is not None:
            estimate.cefr = mastery_to_cefr(estimate.mastery)
        return estimate

    def _status(self, e: SkillEstimate) -> EvidenceStatus:
        cfg = self.config
        if (
            e.mastery is None
            or e.independent_count < cfg.provisional_min_independent
            or e.distinct_items < cfg.provisional_min_items
        ):
            return EvidenceStatus.INSUFFICIENT
        estimated = (
            e.independent_count >= cfg.estimated_min_independent
            and e.distinct_items >= cfg.estimated_min_items
            and e.sessions >= cfg.estimated_min_sessions
            and e.interval_width <= cfg.estimated_max_interval_width
        )
        if not estimated:
            return EvidenceStatus.PROVISIONAL
        if e.validated_observations >= cfg.validated_min_observations:
            return EvidenceStatus.VALIDATED
        return EvidenceStatus.ESTIMATED

    def _coverage(
        self,
        observations: list[Observation],
        groups: dict[str, _Group],
        weights: dict[str, float],
        catalog: list[tuple[str, float | None]] | None,
    ) -> SkillCoverage:
        cfg = self.config
        cov = SkillCoverage(practice_events=len(observations))
        cov.practiced_items = len({o.item_key for o in observations if o.kind != "ignored"})
        cov.assessed_items = len({g.item_key for g in groups.values()})
        cov.assessed_objectives = len(
            {m.objective_id for g in groups.values() for m in g.members if m.objective_id}
        )
        cov.assessed_subskills = len(
            {m.subskill for g in groups.values() for m in g.members if m.subskill}
        )

        def outcomes(key_of: Any) -> dict[str, float]:
            num: dict[str, float] = defaultdict(float)
            den: dict[str, float] = defaultdict(float)
            for g in groups.values():
                key = key_of(g)
                if key is None:
                    continue
                w = max(weights.get(g.key, 0.0), 1e-9)
                num[key] += w * g.signal
                den[key] += w
            return {k: num[k] / den[k] for k in num}

        item_outcome = outcomes(lambda g: g.item_key)
        cov.demonstrated_items = sum(
            1 for v in item_outcome.values() if v >= cfg.demonstrated_threshold
        )
        cov.struggling_items = sum(
            1 for v in item_outcome.values() if v <= cfg.struggling_threshold
        )
        objective_outcome = outcomes(lambda g: g.lead.objective_id)
        cov.demonstrated_objective_ids = sorted(
            k for k, v in objective_outcome.items() if v >= cfg.demonstrated_threshold
        )
        cov.struggling_objective_ids = sorted(
            k for k, v in objective_outcome.items() if v <= cfg.struggling_threshold
        )
        cov.demonstrated_objectives = len(cov.demonstrated_objective_ids)
        if catalog:
            ids = {oid for oid, _ in catalog}
            assessed = {oid for oid in objective_outcome if oid in ids}
            cov.catalog_size = len(ids)
            cov.catalog_assessed = len(assessed)
            cov.catalog_demonstrated = len(set(cov.demonstrated_objective_ids) & ids)
            cov.unassessed_objectives = [
                oid
                for oid, _ in sorted(
                    catalog, key=lambda c: (c[1] if c[1] is not None else 1.0, c[0])
                )
                if oid not in assessed
            ]
        return cov

    @staticmethod
    def _baseline(skill: str, rows: list[dict[str, Any]]) -> float | None:
        """The legacy incremental engine replayed over the same evidence."""
        if not rows:
            return None
        belief = MasteryEngine().update_skill(SkillBelief(skill=skill), rows)
        if belief.sample_size <= 0:
            return None
        return belief.mastery

    def _digest(self, skill: str, event_ids: list[str]) -> str:
        blob = "|".join([METHOD, self.config.digest(), skill, *event_ids])
        return hashlib.sha256(blob.encode()).hexdigest()[:32]
