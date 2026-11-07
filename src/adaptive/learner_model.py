"""Subskill-level learner model (``lkm-subskill-v1``, ADR-0033).

Extends the skill-level ``lkm-evidence-v2`` engine
(:mod:`src.learner.estimation`) down to subskills and learning objectives
(for grammar, one construction each). It does not replace v2: the skill
ability, its weights and all evidence handling are v2's. This module adds:

- **subskill offsets.** Each subskill has a latent offset ``delta`` from its
  skill's ability, ``theta_sub = theta_skill + delta``, with
  ``delta ~ Normal(0, offset_prior_sd**2)``. ``delta`` is fitted on the
  subskill's own evidence by the same weighted MAP as v2, holding the skill
  ability fixed (two-stage empirical Bayes). With no subskill evidence the
  offset is 0 and its full prior uncertainty is kept, so a subskill never
  inherits a falsely confident estimate.
- **subskill recency.** On top of v2's weights, a subskill's older evidence
  decays with ``subskill_half_life_days``, measured from that subskill's
  newest evidence. Knowledge of one construction changes faster than a whole
  skill.
- **performance pattern.** The latest session is compared with the earlier
  ones, so the model can tell a temporary dip (one bad session) from a
  persistent decline (two in a row) or a persistent weakness.
- **predictions.** ``P(success)`` on a task of a given difficulty, with an
  interval, from ``sigmoid(theta_sub - b)``, plus the posterior probability
  that an objective is mastered.

Like v2, everything is a pure function of the evidence rows: no I/O, no clock.
:func:`evidence_before` is the leakage guard for every prediction: only
evidence created strictly before ``as_of`` is used.

The default configuration was chosen by the held-out comparison in
``evals/adaptive`` (see ``docs/adaptive-learning.md``). Those results come
from simulated learners, so the parameters are provisional until they can be
re-fitted on real learner data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.learner.estimation import (
    DEFAULT_CONFIG,
    EngineConfig,
    EvidenceMasteryEngine,
    EvidenceStatus,
    Observation,
    SkillEstimate,
    fit_ability,
    to_observation,
)

#: Method tag for subskill estimates and predictions.
METHOD = "lkm-subskill-v1"

#: Success probability that counts as "mastered" for objective completion.
MASTERY_SUCCESS_TARGET = 0.8


@dataclass(frozen=True)
class SubskillConfig:
    """Tunable assumptions of the subskill layer."""

    #: Prior SD of a subskill's offset from its skill (logits).
    offset_prior_sd: float = 1.0
    #: Half-life of subskill evidence, in days from the subskill's newest evidence.
    subskill_half_life_days: float = 21.0
    #: z for intervals.
    interval_z: float = 1.96
    #: Independent observations / sessions for a subskill to leave
    #: ``insufficient_evidence`` / reach ``estimated``.
    provisional_min_independent: int = 2
    estimated_min_independent: int = 6
    estimated_min_sessions: int = 2
    #: How many SEs a session must deviate from the earlier sessions to count
    #: as a dip or an improvement.
    pattern_z: float = 1.64
    #: Mastery (at reference difficulty) below which, with at least
    #: provisional evidence and no improvement, a subskill is a weakness.
    weakness_mastery: float = 0.4


DEFAULT_SUBSKILL_CONFIG = SubskillConfig()


class Pattern:
    """Performance pattern labels (strings, so they serialize as-is)."""

    INSUFFICIENT = "insufficient_evidence"
    #: All evidence is from one session: a dip and a weakness look the same.
    SINGLE_SESSION = "single_session"
    STABLE = "stable"
    IMPROVING = "improving"
    TEMPORARY_DIP = "temporary_dip"
    PERSISTENT_DECLINE = "persistent_decline"
    PERSISTENT_WEAKNESS = "persistent_weakness"


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = min(1.0 - 1e-9, max(1e-9, p))
    return math.log(p / (1.0 - p))


def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def difficulty_logit(difficulty: float | None, config: EngineConfig = DEFAULT_CONFIG) -> float:
    """Map a ``[0, 1]`` task difficulty to the engine's logit scale (unknown -> 0)."""
    if difficulty is None:
        return 0.0
    return config.difficulty_scale * (max(0.0, min(1.0, difficulty)) - 0.5)


def logit_to_difficulty(b: float, config: EngineConfig = DEFAULT_CONFIG) -> float:
    """Inverse of :func:`difficulty_logit`, clipped to ``[0, 1]``."""
    return max(0.0, min(1.0, b / config.difficulty_scale + 0.5))


def _parse_time(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def evidence_before(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """The leakage guard: keep only rows created strictly before ``as_of``.

    ``as_of=None`` keeps every row (the "now" view). Rows with an unparseable
    timestamp are dropped when a cut-off is given, since they cannot be placed
    before it.
    """
    if as_of is None:
        return list(rows)
    cutoff = _parse_time(as_of)
    if cutoff is None:
        raise ValueError(f"unparseable as_of timestamp: {as_of!r}")
    kept = []
    for row in rows:
        ts = _parse_time(row.get("created_at"))
        if ts is not None and ts < cutoff:
            kept.append(row)
    return kept


@dataclass
class SubskillEstimate:
    """The model's view of one subskill (for grammar: one construction)."""

    skill: str
    subskill: str
    objective_id: str | None
    method: str = METHOD
    status: str = EvidenceStatus.INSUFFICIENT.value
    #: Skill ability + offset (logits) and its SE.
    ability: float = 0.0
    ability_se: float = 1.5
    offset: float = 0.0
    offset_se: float = 1.0
    #: Success probability on a reference task (difficulty 0.5), with interval.
    mastery: float | None = None
    mastery_low: float | None = None
    mastery_high: float | None = None
    independent_count: int = 0
    sessions: int = 0
    pattern: str = Pattern.INSUFFICIENT
    #: The latest session's ability shift relative to earlier sessions (logits).
    recent_shift: float | None = None
    recent_shift_se: float | None = None
    last_evidence_at: str | None = None
    event_ids: list[str] = field(default_factory=list)

    @property
    def uncertainty(self) -> float:
        """SE relative to the engine's prior SD (1.0 = nothing learned)."""
        return min(1.0, self.ability_se / DEFAULT_CONFIG.prior_sd)

    def p_success(self, difficulty: float | None, *, z: float = 1.96) -> tuple[float, float, float]:
        """``(p, low, high)`` of success on a task of the given difficulty."""
        b = difficulty_logit(difficulty)
        return (
            _sigmoid(self.ability - b),
            _sigmoid(self.ability - b - z * self.ability_se),
            _sigmoid(self.ability - b + z * self.ability_se),
        )

    def mastery_probability(self, difficulty: float | None) -> float:
        """Posterior probability that success on this difficulty is at least
        :data:`MASTERY_SUCCESS_TARGET` (normal approximation to the posterior)."""
        b = difficulty_logit(difficulty)
        margin = self.ability - b - _logit(MASTERY_SUCCESS_TARGET)
        return _phi(margin / max(self.ability_se, 1e-6))

    def as_dict(self) -> dict[str, Any]:
        def r(v: float | None) -> float | None:
            return None if v is None else round(v, 4)

        return {
            "skill": self.skill,
            "subskill": self.subskill,
            "objective_id": self.objective_id,
            "method": self.method,
            "status": self.status,
            "ability": r(self.ability),
            "ability_se": r(self.ability_se),
            "offset": r(self.offset),
            "offset_se": r(self.offset_se),
            "mastery": r(self.mastery),
            "mastery_low": r(self.mastery_low),
            "mastery_high": r(self.mastery_high),
            "uncertainty": r(self.uncertainty),
            "independent_count": self.independent_count,
            "sessions": self.sessions,
            "pattern": self.pattern,
            "recent_shift": r(self.recent_shift),
            "recent_shift_se": r(self.recent_shift_se),
            "last_evidence_at": self.last_evidence_at,
            "event_ids": list(self.event_ids),
        }


@dataclass
class LearnerEstimates:
    """Skill-level (v2) and subskill-level (v1) estimates for one learner."""

    skills: dict[str, SkillEstimate]
    subskills: dict[tuple[str, str], SubskillEstimate]

    def subskill(self, skill: str, subskill: str | None) -> SubskillEstimate:
        """The subskill estimate, or a prior-only one built from the skill."""
        if subskill is not None and (skill, subskill) in self.subskills:
            return self.subskills[(skill, subskill)]
        return prior_subskill(self.skills.get(skill), skill, subskill or skill)


def prior_subskill(
    skill_estimate: SkillEstimate | None,
    skill: str,
    subskill: str,
    config: SubskillConfig = DEFAULT_SUBSKILL_CONFIG,
) -> SubskillEstimate:
    """A subskill with no evidence of its own: the skill's ability, offset 0,
    and the offset's full prior uncertainty added to the skill's SE."""
    theta = 0.0
    se = DEFAULT_CONFIG.prior_sd
    if skill_estimate is not None and skill_estimate.ability is not None:
        theta = skill_estimate.ability
        se = math.sqrt((skill_estimate.ability_se or se) ** 2 + config.offset_prior_sd**2)
    return SubskillEstimate(
        skill=skill,
        subskill=subskill,
        objective_id=f"{skill}.{subskill}" if subskill != skill else None,
        ability=theta,
        ability_se=se,
        offset=0.0,
        offset_se=config.offset_prior_sd,
        mastery=None,
    )


@dataclass
class _Counted:
    """One independent observation (a v2 group) as the subskill layer sees it."""

    event_id: str
    subskill: str | None
    objective_id: str | None
    session_id: str
    timestamp: float | None
    signal: float
    b: float
    weight: float


class SubskillModel:
    """Computes v2 skill estimates plus v1 subskill estimates."""

    def __init__(
        self,
        engine: EvidenceMasteryEngine | None = None,
        config: SubskillConfig | None = None,
    ) -> None:
        self.engine = engine or EvidenceMasteryEngine()
        self.config = config or DEFAULT_SUBSKILL_CONFIG

    def estimate(
        self,
        rows: list[dict[str, Any]],
        *,
        catalogs: dict[str, list[tuple[str, float | None]]] | None = None,
    ) -> LearnerEstimates:
        skills = self.engine.estimate_all(rows, catalogs=catalogs, with_contributions=True)
        observations: dict[str, Observation] = {}
        for row in rows:
            o = to_observation(row)
            if o is not None:
                observations[o.event_id] = o
        subskills: dict[tuple[str, str], SubskillEstimate] = {}
        for skill, est in skills.items():
            if est.ability is None:
                continue
            counted = [
                _Counted(
                    event_id=c.event_id,
                    subskill=observations[c.event_id].subskill,
                    objective_id=observations[c.event_id].objective_id,
                    session_id=observations[c.event_id].session_id or "(none)",
                    timestamp=observations[c.event_id].timestamp,
                    signal=float(c.signal or 0.0),
                    b=c.difficulty_logit,
                    weight=c.weight,
                )
                for c in est.contributions
                if c.role == "counted" and c.event_id in observations
            ]
            by_sub: dict[str, list[_Counted]] = {}
            for c in counted:
                if c.subskill:
                    by_sub.setdefault(c.subskill, []).append(c)
            for sub, items in sorted(by_sub.items()):
                subskills[(skill, sub)] = self._fit_subskill(est, sub, items)
        return LearnerEstimates(skills=skills, subskills=subskills)

    def _fit_subskill(
        self, skill_est: SkillEstimate, subskill: str, items: list[_Counted]
    ) -> SubskillEstimate:
        cfg = self.config
        assert skill_est.ability is not None and skill_est.ability_se is not None
        theta_s, se_s = skill_est.ability, skill_est.ability_se
        newest = max((c.timestamp for c in items if c.timestamp is not None), default=None)

        def weight(c: _Counted) -> float:
            if newest is None or c.timestamp is None or math.isinf(cfg.subskill_half_life_days):
                return c.weight
            age = max(0.0, (newest - c.timestamp) / 86400.0)
            return float(c.weight * 0.5 ** (age / cfg.subskill_half_life_days))

        data = [(c.signal, c.b - theta_s, weight(c)) for c in items]
        delta, se_d = fit_ability(data, prior_sd=cfg.offset_prior_sd)
        ability = theta_s + delta
        se = math.sqrt(se_s**2 + se_d**2)
        z = cfg.interval_z
        sessions = sorted({c.session_id for c in items})
        objective = next((c.objective_id for c in items if c.objective_id), None)
        est = SubskillEstimate(
            skill=skill_est.skill,
            subskill=subskill,
            objective_id=objective or f"{skill_est.skill}.{subskill}",
            ability=ability,
            ability_se=se,
            offset=delta,
            offset_se=se_d,
            mastery=_sigmoid(ability),
            mastery_low=_sigmoid(ability - z * se),
            mastery_high=_sigmoid(ability + z * se),
            independent_count=len(items),
            sessions=len(sessions),
            event_ids=sorted(c.event_id for c in items),
        )
        stamps = [c.timestamp for c in items if c.timestamp is not None]
        if stamps:
            est.last_evidence_at = datetime.fromtimestamp(max(stamps), tz=UTC).isoformat()
        if len(items) < cfg.provisional_min_independent:
            est.status = EvidenceStatus.INSUFFICIENT.value
        elif (
            len(items) >= cfg.estimated_min_independent
            and len(sessions) >= cfg.estimated_min_sessions
        ):
            est.status = EvidenceStatus.ESTIMATED.value
        else:
            est.status = EvidenceStatus.PROVISIONAL.value
        self._pattern(est, items, theta_s)
        return est

    def _session_order(self, items: list[_Counted]) -> list[str]:
        """Sessions ordered by their newest evidence (then id, for determinism)."""
        last: dict[str, float] = {}
        for c in items:
            t = c.timestamp if c.timestamp is not None else 0.0
            last[c.session_id] = max(last.get(c.session_id, t), t)
        return sorted(last, key=lambda s: (last[s], s))

    def _shift(
        self, recent: list[_Counted], earlier: list[_Counted], theta_s: float
    ) -> tuple[float, float, float]:
        """Fit the earlier sessions, then the recent session's shift from them.

        Returns ``(earlier_ability, shift, shift_se)``. The shift's prior is
        the offset prior, so a handful of outcomes cannot produce a large,
        confident shift.
        """
        cfg = self.config
        delta_e, _ = fit_ability(
            [(c.signal, c.b - theta_s, c.weight) for c in earlier], prior_sd=cfg.offset_prior_sd
        )
        base = theta_s + delta_e
        shift, se = fit_ability(
            [(c.signal, c.b - base, c.weight) for c in recent], prior_sd=cfg.offset_prior_sd
        )
        return base, shift, se

    def _pattern(self, est: SubskillEstimate, items: list[_Counted], theta_s: float) -> None:
        cfg = self.config
        if est.status == EvidenceStatus.INSUFFICIENT.value:
            est.pattern = Pattern.INSUFFICIENT
            return
        order = self._session_order(items)
        weak = est.mastery is not None and est.mastery < cfg.weakness_mastery
        if len(order) < 2:
            est.pattern = Pattern.SINGLE_SESSION
            return
        last = order[-1]
        recent = [c for c in items if c.session_id == last]
        earlier = [c for c in items if c.session_id != last]
        _, shift, se = self._shift(recent, earlier, theta_s)
        est.recent_shift, est.recent_shift_se = shift, se
        drop = shift < -cfg.pattern_z * se
        rise = shift > cfg.pattern_z * se
        if drop and len(order) >= 3:
            prev = order[-2]
            prior = [c for c in items if c.session_id not in (last, prev)]
            prev_items = [c for c in items if c.session_id == prev]
            _, prev_shift, prev_se = self._shift(prev_items, prior, theta_s)
            if prev_shift < -cfg.pattern_z * prev_se:
                est.pattern = Pattern.PERSISTENT_DECLINE
                return
        if drop:
            est.pattern = Pattern.TEMPORARY_DIP
        elif rise:
            est.pattern = Pattern.IMPROVING
        elif weak:
            est.pattern = Pattern.PERSISTENT_WEAKNESS
        else:
            est.pattern = Pattern.STABLE


@dataclass(frozen=True)
class Prediction:
    """A model prediction, never to be confused with an observed result."""

    kind: str  # always "prediction"
    method: str
    skill: str
    subskill: str | None
    difficulty: float | None
    p_success: float
    p_low: float
    p_high: float
    basis: str  # "subskill" | "skill_prior" | "population_prior"
    status: str
    as_of: str | None
    evidence_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "method": self.method,
            "skill": self.skill,
            "subskill": self.subskill,
            "difficulty": self.difficulty,
            "p_success": round(self.p_success, 4),
            "interval": [round(self.p_low, 4), round(self.p_high, 4)],
            "basis": self.basis,
            "status": self.status,
            "as_of": self.as_of,
            "evidence_ids": list(self.evidence_ids),
        }


def predict_success(
    estimates: LearnerEstimates,
    skill: str,
    subskill: str | None,
    difficulty: float | None,
    *,
    as_of: str | None = None,
) -> Prediction:
    """Predict success on a task from already-computed estimates.

    The caller must have built ``estimates`` from :func:`evidence_before`
    rows; :func:`predict_from_rows` does both.
    """
    sub = estimates.subskill(skill, subskill)
    skill_est = estimates.skills.get(skill)
    if (skill, subskill or "") in estimates.subskills:
        basis = "subskill"
        status = sub.status
    elif skill_est is not None and skill_est.ability is not None:
        basis = "skill_prior"
        status = EvidenceStatus.INSUFFICIENT.value
    else:
        basis = "population_prior"
        status = EvidenceStatus.INSUFFICIENT.value
    p, low, high = sub.p_success(difficulty)
    return Prediction(
        kind="prediction",
        method=METHOD,
        skill=skill,
        subskill=subskill,
        difficulty=difficulty,
        p_success=p,
        p_low=low,
        p_high=high,
        basis=basis,
        status=status,
        as_of=as_of,
        evidence_ids=tuple(sub.event_ids),
    )


def predict_from_rows(
    rows: list[dict[str, Any]],
    skill: str,
    subskill: str | None,
    difficulty: float | None,
    *,
    as_of: str | None = None,
    model: SubskillModel | None = None,
) -> Prediction:
    """Leakage-safe prediction straight from evidence rows."""
    history = evidence_before(rows, as_of)
    estimates = (model or SubskillModel()).estimate(history)
    return predict_success(estimates, skill, subskill, difficulty, as_of=as_of)
