"""Candidate learner models for the held-out comparison (ADR-0033).

All candidates share one online protocol. For each learner, ``predict(row)``
is called *before* ``observe(row)``, so a prediction only ever sees earlier
evidence. Parameters come from ``fit(train_logs)``, which only sees the
training learners. Rows are app-visible evidence rows; the hidden
ground-truth keys are stripped before they reach a model.

Candidates:

- ``legacy_incremental`` — the pre-ADR-0031 ``MasteryEngine`` (skill level,
  no difficulty);
- ``lkm_v2_rasch`` — the current ``lkm-evidence-v2`` engine (skill level,
  difficulty-aware): the **baseline**;
- ``bkt`` — Bayesian Knowledge Tracing, one knowledge component per
  subskill; parameters are literature defaults (cold) or grid-search
  maximum likelihood on the training learners (warm);
- ``elo`` — Elo learner–item model with skill and subskill abilities and
  uncertainty-decayed K; item difficulties start at the labels and are
  learned from the training learners (warm);
- ``lkm_subskill_v1`` — the new production model
  (:mod:`src.adaptive.learner_model`); its hyperparameters are tuned on the
  training learners (warm).

Only the selected model is used by the app. BKT and Elo exist here, for
evaluation, not in ``src/``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.adaptive.learner_model import (
    SubskillConfig,
    SubskillModel,
    difficulty_logit,
    predict_success,
)
from src.learner.estimation import EvidenceMasteryEngine
from src.learner.mastery_engine import MasteryEngine, SkillBelief
from src.util import sigmoid

_SIGNAL = {"correct": 1.0, "incorrect": 0.0}


def outcome(row: dict[str, Any]) -> float | None:
    return _SIGNAL.get(str(row.get("assessment") or "").lower())


class Predictor(Protocol):
    def predict(self, row: dict[str, Any]) -> float: ...
    def observe(self, row: dict[str, Any]) -> None: ...


class Candidate(Protocol):
    name: str

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None: ...
    def learner(self) -> Predictor: ...


# --- legacy -----------------------------------------------------------------


@dataclass
class _LegacyLearner:
    beliefs: dict[str, SkillBelief] = field(default_factory=dict)
    engine: MasteryEngine = field(default_factory=MasteryEngine)

    def predict(self, row: dict[str, Any]) -> float:
        b = self.beliefs.get(str(row["skill"]))
        return 0.5 if b is None or b.sample_size <= 0 else b.mastery

    def observe(self, row: dict[str, Any]) -> None:
        skill = str(row["skill"])
        prior = self.beliefs.get(skill, SkillBelief(skill=skill))
        self.beliefs[skill] = self.engine.update_skill(prior, [row])


class LegacyIncremental:
    name = "legacy_incremental"

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None:
        return None

    def learner(self) -> Predictor:
        return _LegacyLearner()


# --- lkm-evidence-v2 (baseline) ----------------------------------------------


@dataclass
class _RaschLearner:
    history: list[dict[str, Any]] = field(default_factory=list)
    engine: EvidenceMasteryEngine = field(default_factory=EvidenceMasteryEngine)
    _cache: dict[str, Any] = field(default_factory=dict)

    def predict(self, row: dict[str, Any]) -> float:
        skill = str(row["skill"])
        key = f"{skill}:{len(self.history)}"
        if key not in self._cache:
            rows = [r for r in self.history if r.get("skill") == skill]
            self._cache = {key: self.engine.estimate_all(rows).get(skill)}
        est = self._cache[key]
        theta = 0.0 if est is None or est.ability is None else est.ability
        return sigmoid(theta - difficulty_logit(row.get("difficulty")))

    def observe(self, row: dict[str, Any]) -> None:
        self.history.append(row)


class RaschV2:
    name = "lkm_v2_rasch"

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None:
        return None

    def learner(self) -> Predictor:
        return _RaschLearner()


# --- lkm-subskill-v1 (new) -----------------------------------------------------


@dataclass
class _SubskillLearner:
    model: SubskillModel
    history: list[dict[str, Any]] = field(default_factory=list)
    _cache: dict[str, Any] = field(default_factory=dict)

    def predict(self, row: dict[str, Any]) -> float:
        skill = str(row["skill"])
        key = f"{skill}:{len(self.history)}"
        if key not in self._cache:
            rows = [r for r in self.history if r.get("skill") == skill]
            self._cache = {key: self.model.estimate(rows)}
        return self.interval(row)[0]

    def interval(self, row: dict[str, Any]) -> tuple[float, float, float]:
        """``(p, low, high)`` for the row's task (uses the same cache)."""
        skill = str(row["skill"])
        key = f"{skill}:{len(self.history)}"
        if key not in self._cache:
            rows = [r for r in self.history if r.get("skill") == skill]
            self._cache = {key: self.model.estimate(rows)}
        pred = predict_success(self._cache[key], skill, row.get("subskill"), row.get("difficulty"))
        return pred.p_success, pred.p_low, pred.p_high

    def observe(self, row: dict[str, Any]) -> None:
        self.history.append(row)


@dataclass
class SubskillV1:
    name: str = "lkm_subskill_v1"
    config: SubskillConfig = field(default_factory=SubskillConfig)
    #: Grid of (half-life days, offset prior SD) tried by ``fit`` when tuning.
    tune: bool = False
    grid: tuple[tuple[float, float], ...] = (
        (7.0, 1.0),
        (21.0, 1.0),
        (60.0, 1.0),
        (math.inf, 1.0),
        (21.0, 0.5),
        (21.0, 1.5),
    )
    tuning_log: list[dict[str, float]] = field(default_factory=list)

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None:
        if not self.tune or not train_logs:
            return
        best: tuple[float, SubskillConfig] | None = None
        for half_life, sd in self.grid:
            cfg = SubskillConfig(subskill_half_life_days=half_life, offset_prior_sd=sd)
            loss = _log_loss_on(train_logs, lambda c=cfg: _SubskillLearner(SubskillModel(config=c)))
            self.tuning_log.append(
                {"half_life_days": half_life, "offset_prior_sd": sd, "train_log_loss": loss}
            )
            if best is None or loss < best[0]:
                best = (loss, cfg)
        assert best is not None
        self.config = best[1]

    def learner(self) -> Predictor:
        return _SubskillLearner(SubskillModel(config=self.config))


# --- BKT --------------------------------------------------------------------


@dataclass(frozen=True)
class BKTParams:
    p_init: float = 0.3
    p_learn: float = 0.1
    p_slip: float = 0.1
    p_guess: float = 0.2

    def predict(self, p_known: float) -> float:
        return p_known * (1.0 - self.p_slip) + (1.0 - p_known) * self.p_guess

    def update(self, p_known: float, y: float) -> float:
        p_correct = self.predict(p_known)
        post_c = p_known * (1.0 - self.p_slip) / max(p_correct, 1e-12)
        post_w = p_known * self.p_slip / max(1.0 - p_correct, 1e-12)
        post = y * post_c + (1.0 - y) * post_w
        return post + (1.0 - post) * self.p_learn


def _kc(row: dict[str, Any]) -> str:
    return f"{row.get('skill')}:{row.get('subskill') or row.get('skill')}"


@dataclass
class _BKTLearner:
    params: dict[str, BKTParams]
    default: BKTParams
    state: dict[str, float] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)

    def _p(self, kc: str) -> BKTParams:
        return self.params.get(kc, self.default)

    def predict(self, row: dict[str, Any]) -> float:
        kc = _kc(row)
        p = self._p(kc)
        return p.predict(self.state.get(kc, p.p_init))

    def observe(self, row: dict[str, Any]) -> None:
        y = outcome(row)
        corr = row.get("correlation_id")
        if y is None or (corr and corr in self.seen):
            return
        if corr:
            self.seen.add(corr)
        kc = _kc(row)
        p = self._p(kc)
        self.state[kc] = p.update(self.state.get(kc, p.p_init), y)


def _bkt_sequences(train_logs: list[list[dict[str, Any]]]) -> dict[str, list[list[float]]]:
    seqs: dict[str, list[list[float]]] = defaultdict(list)
    for log in train_logs:
        per_kc: dict[str, list[float]] = defaultdict(list)
        seen: set[str] = set()
        for row in log:
            y = outcome(row)
            corr = row.get("correlation_id")
            if y is None or (corr and corr in seen):
                continue
            if corr:
                seen.add(corr)
            per_kc[_kc(row)].append(y)
        for kc, seq in per_kc.items():
            seqs[kc].append(seq)
    return seqs


def _bkt_loglik(params: BKTParams, seqs: list[list[float]]) -> float:
    ll = 0.0
    for seq in seqs:
        pk = params.p_init
        for y in seq:
            p = min(1 - 1e-6, max(1e-6, params.predict(pk)))
            ll += y * math.log(p) + (1 - y) * math.log(1 - p)
            pk = params.update(pk, y)
    return ll


@dataclass
class BKT:
    name: str = "bkt"
    tune: bool = False
    min_sequences: int = 8
    default: BKTParams = field(default_factory=BKTParams)
    params: dict[str, BKTParams] = field(default_factory=dict)

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None:
        if not self.tune:
            return
        seqs = _bkt_sequences(train_logs)
        grid = [
            BKTParams(i, t, s, g)
            for i in (0.1, 0.25, 0.4, 0.55, 0.7)
            for t in (0.02, 0.06, 0.12, 0.2, 0.3)
            for s in (0.05, 0.1, 0.2)
            for g in (0.05, 0.15, 0.25, 0.35)
        ]

        def best(seq_list: list[list[float]]) -> BKTParams:
            return max(grid, key=lambda p: _bkt_loglik(p, seq_list))

        pooled = [s for kc_seqs in seqs.values() for s in kc_seqs]
        self.default = best(pooled) if pooled else self.default
        for kc, kc_seqs in seqs.items():
            if len(kc_seqs) >= self.min_sequences:
                self.params[kc] = best(kc_seqs)

    def learner(self) -> Predictor:
        return _BKTLearner(self.params, self.default)


# --- Elo --------------------------------------------------------------------


@dataclass
class _EloLearner:
    item_offsets: dict[str, float]
    k_skill: float
    k_sub: float
    decay: float
    theta: dict[str, float] = field(default_factory=dict)
    sub: dict[str, float] = field(default_factory=dict)
    n: dict[str, int] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)

    def _b(self, row: dict[str, Any]) -> float:
        return difficulty_logit(row.get("difficulty")) + self.item_offsets.get(
            str(row.get("item_id")), 0.0
        )

    def predict(self, row: dict[str, Any]) -> float:
        skill = str(row["skill"])
        return sigmoid(self.theta.get(skill, 0.0) + self.sub.get(_kc(row), 0.0) - self._b(row))

    def observe(self, row: dict[str, Any]) -> None:
        y = outcome(row)
        corr = row.get("correlation_id")
        if y is None or (corr and corr in self.seen):
            return
        if corr:
            self.seen.add(corr)
        skill, kc = str(row["skill"]), _kc(row)
        err = y - self.predict(row)
        ns, nk = self.n.get(skill, 0), self.n.get(kc, 0)
        self.theta[skill] = self.theta.get(skill, 0.0) + self.k_skill / (1 + self.decay * ns) * err
        self.sub[kc] = self.sub.get(kc, 0.0) + self.k_sub / (1 + self.decay * nk) * err
        self.n[skill], self.n[kc] = ns + 1, nk + 1


@dataclass
class Elo:
    name: str = "elo"
    tune: bool = False
    k_skill: float = 0.4
    k_sub: float = 0.8
    decay: float = 0.05
    k_item: float = 0.3
    item_offsets: dict[str, float] = field(default_factory=dict)

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None:
        if not self.tune:
            return
        counts: dict[str, int] = defaultdict(int)
        for _epoch in range(2):
            for log in train_logs:
                learner = _EloLearner(self.item_offsets, self.k_skill, self.k_sub, self.decay)
                for row in log:
                    y = outcome(row)
                    if y is None:
                        continue
                    item = str(row.get("item_id"))
                    err = y - learner.predict(row)
                    k = self.k_item / (1 + 0.05 * counts[item])
                    self.item_offsets[item] = self.item_offsets.get(item, 0.0) - k * err
                    counts[item] += 1
                    learner.observe(row)

    def learner(self) -> Predictor:
        return _EloLearner(dict(self.item_offsets), self.k_skill, self.k_sub, self.decay)


# --- shared ------------------------------------------------------------------


def _log_loss_on(logs: list[list[dict[str, Any]]], make: Any) -> float:
    """Mean online log loss of fresh predictors over training logs (for tuning).

    Training targets are the *observed* (graded) outcomes, since hidden truth
    is not available to fitting.
    """
    total, n = 0.0, 0
    for log in logs:
        learner = make()
        seen: set[str] = set()
        for row in log:
            y = outcome(row)
            corr = row.get("correlation_id")
            first = not corr or corr not in seen
            if corr:
                seen.add(corr)
            if y is not None and first:
                p = min(1 - 1e-6, max(1e-6, learner.predict(row)))
                total -= y * math.log(p) + (1 - y) * math.log(1 - p)
                n += 1
            learner.observe(row)
    return total / n if n else math.inf


def all_candidates(*, warm: bool) -> list[Candidate]:
    """The candidate set: cold = no training data used; warm = fitted on it."""
    return [
        LegacyIncremental(),
        RaschV2(),
        BKT(tune=warm),
        Elo(tune=warm),
        SubskillV1(tune=warm),
    ]
