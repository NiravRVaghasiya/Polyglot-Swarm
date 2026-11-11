"""Planner outcome simulation (Checkpoint 6) — SIMULATED learners only.

Compares four ways of choosing what a learner practises. Each faces the same
simulated learners, with common random numbers.

1. ``static``: a fixed syllabus.
   - Constructions in CEFR order, two sessions each, at the content level.
   - Three new words a session.
   - Reviews of the words introduced in the last two sessions.
2. ``adaptive``: the engine with prediction, difficulty adaptation and
   FSRS integration switched off. That leaves skill-level v2 estimates, the
   content-level difficulty and legacy FSRS (meeting a word counts as a
   ``Good`` review, and every review is rated ``Good`` or ``Again``).
3. ``adaptive_predictive``: plus subskill predictions and adaptive
   difficulty.
4. ``adaptive_full``: plus FSRS integration.
   - Exposure is not recall.
   - Reviews progress from recognition to production.
   - Leeches are remediated.
   - Review urgency is retention-aware.

Every policy plans once per session, within the same time budget and action
cap. The simulated world has only grammar and vocabulary, so every planner is
told to avoid the other skills.

Measured per learner, and compared with paired bootstrap intervals:

- **Immediate performance:** true outcomes during sessions, and
  difficulty-adjusted success (success above what item difficulty alone
  predicts).
- **Mastery progression:** true recall gain on curriculum constructions over
  the course.
- **Delayed retention:** true recall ``delay_days`` after the last session,
  with no practice in between, for constructions and introduced words. Also
  the share of end-of-course knowledge still held.
- **Objective completion:** constructions with true success of at least 0.8,
  at the end and after the delay.
- **Learning efficiency:** construction recall gain, and delayed words held,
  per practice hour.
- **Recommendation relevance:** an oracle judges each executed practice or
  review. It is relevant unless it practised something the learner had
  already mastered (true success above 0.95), something overwhelming (below
  0.3), or reviewed an item still at least 97% recalled.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from fsrs import Card, Rating, Scheduler

from evals.adaptive.model_eval import auc, brier, ece, log_loss
from evals.adaptive.simulator import (
    T0,
    GeneratorConfig,
    Grader,
    SimLearner,
    SimObjective,
    World,
    _uniform,
    build_world,
    session_days,
    visible,
)
from src.adaptive.constraints import PlanConstraints
from src.adaptive.memory import live_retrievability, rating_for
from src.adaptive.planner import PlannerConfig, Recommendation
from src.adaptive.planner import plan as adaptive_plan
from src.adaptive.snapshot import CatalogObjective, LearnerSnapshot
from src.learner.cefr_bands import CEFR_ORDER

POLICIES = ("static", "adaptive", "adaptive_predictive", "adaptive_full")
#: Policy every other one is compared against, paired per learner. Until the
#: old curriculum planner was removed (single planner), the baseline was that
#: planner (``existing_planner``); results recorded before then use it.
BASELINE = "static"
AVOID = frozenset({"listening", "reading", "writing", "pragmatics", "speaking"})
_SCHEDULER = Scheduler()
FIRST_RETRIEVAL_DELAY = timedelta(minutes=10)


@dataclass(frozen=True)
class PolicyEvalConfig:
    n_learners: int = 40
    n_sessions: int = 20
    session_minutes: float = 20.0
    max_actions: int = 8
    delay_days: float = 30.0
    gain_peak: float | None = 0.7
    family: str = "continuous"
    target_cefr: str = "B1"
    world_seed: int = 7
    seed: int = 20261107
    bootstrap_samples: int = 1000
    policies: tuple[str, ...] = POLICIES


# --- the simulated environment ------------------------------------------------------


@dataclass
class Env:
    learner: SimLearner
    grader: Grader
    world: World
    legacy_fsrs: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    introduced: list[str] = field(default_factory=list)  # objective ids, in order
    t: float = 0.0
    session: int = 0
    minutes: float = 0.0
    log: list[dict[str, Any]] = field(default_factory=list)
    predictions: list[tuple[float, float]] = field(default_factory=list)

    @property
    def sid(self) -> str:
        return f"{self.learner.learner_id}-s{self.session}"

    def now(self) -> Any:
        return T0 + timedelta(days=self.t)

    def _advance(self, minutes: float) -> None:
        self.t += minutes / 1440.0
        self.minutes += minutes

    # --- actions ---

    def _attempt(
        self,
        obj: SimObjective,
        tier: str,
        *,
        task: str,
        reliability: float,
        feedback: bool = True,
        item_level: bool = True,
        predicted: float | None = None,
    ) -> bool:
        items = obj.items_of(tier)
        n = sum(
            1 for r in self.rows if r.get("payload", {}).get("sim_objective") == obj.objective_id
        )
        item = items[n % len(items)]
        p_true = self.learner.p_success(item, self.t, self.learner.session_offset(self.session))
        p_clean = self.learner.p_success(item, self.t, 0.0)
        success, _ = self.learner.attempt(item, self.t, self.session, feedback=feedback)
        self.rows += self.grader.graded(
            self.learner.learner_id,
            obj,
            item,
            success,
            p_true,
            self.t,
            self.sid,
            task_type=task,
            reliability=reliability,
            item_level=item_level,
        )
        self.log.append(
            {
                "kind": "attempt",
                "objective": obj.objective_id,
                "tier": tier,
                "success": success,
                "p_clean": p_clean,
                "pop_p": _population_p(self.learner, item),
                "skill": obj.skill,
            }
        )
        if predicted is not None:
            self.predictions.append((predicted, 1.0 if success else 0.0))
        self.t += 0.0005
        return success

    def practice(
        self, oid: str, difficulty: float | None, *, predicted: float | None = None
    ) -> None:
        obj = self.world.objectives[oid]
        tier = _tier_for(obj, difficulty)
        self._judge("practice", oid, tier)
        for _ in range(3):
            self._attempt(obj, tier, task="exercise", reliability=0.95, predicted=predicted)
        self._advance(5.0)

    def diagnostic(self, oid: str) -> None:
        obj = self.world.objectives[oid]
        self.log.append(
            {"kind": "action", "action": "diagnostic", "objective": oid, "relevant": None}
        )
        for _ in range(2):
            self._attempt(obj, "medium", task="diagnostic", reliability=0.95, feedback=False)
        self._advance(3.0)

    def review(self, oid: str, mode: str) -> None:
        obj = self.world.objectives[oid]
        if obj.skill == "grammar":
            self._judge("review", oid, "medium")
            self._attempt(obj, "medium", task="review_recall", reliability=0.95)
            self._advance(2.0)
            return
        self._judge("review", oid, mode)
        success = self._attempt(obj, mode, task="review_recall", reliability=0.95)
        card = self.cards.get(oid)
        if card is not None:
            if self.legacy_fsrs:
                rating = Rating.Good if success else Rating.Again
            else:
                rating = rating_for(mode, success)
            c, _ = _SCHEDULER.review_card(Card.from_dict(card["card_state"]), rating, self.now())
            card["card_state"] = dict(c.to_dict())
            card["next_review"] = c.due.isoformat()
        self._advance(1.0)

    def remediate_word(self, oid: str) -> None:
        self.learner.expose(oid, self.t)
        self.review(oid, "production")
        self.review(oid, "production")
        self._advance(1.0)

    def introduce_words(self, count: int) -> list[str]:
        new = [
            o.objective_id
            for o in sorted(self.world.vocabulary(), key=lambda o: o.objective_id)
            if o.objective_id not in self.cards
        ][:count]
        for oid in new:
            obj = self.world.objectives[oid]
            self.learner.expose(oid, self.t)
            self.rows.append(self.grader.exposure(self.learner.learner_id, obj, self.t, self.sid))
            if self.legacy_fsrs:
                card, _ = _SCHEDULER.review_card(Card(), Rating.Good, self.now())
            else:
                card = Card(due=self.now() + FIRST_RETRIEVAL_DELAY)
            self.cards[oid] = {
                "word": obj.subskill,
                "card_state": dict(card.to_dict()),
                "next_review": card.due.isoformat(),
                "created_at": self.now().isoformat(),
            }
            self.introduced.append(oid)
        return new

    def expansion(self, count: int = 3) -> None:
        self.introduce_words(count)
        self._advance(3.0)

    def conversation(self, level: int) -> None:
        self.introduce_words(2)
        grammar = sorted(self.world.grammar(), key=lambda o: o.objective_id)
        band = [o for o in grammar if abs(CEFR_ORDER.index(o.cefr) - level) <= 1] or grammar
        for k in range(2):
            u = _uniform(
                self.learner.seed, self.learner.learner_id, "conv", self.session, k, self.t
            )
            obj = band[int(u * len(band))]
            self._attempt(obj, "medium", task="conversation", reliability=0.75, item_level=False)
        self._advance(8.0)

    # --- oracle relevance ---

    def _judge(self, kind: str, oid: str, tier: str) -> None:
        obj = self.world.objectives[oid]
        item = obj.items_of(tier)[0]
        p = self.learner.p_success(item, self.t, 0.0)
        if kind == "review":
            relevant = self.learner.recall_probability(oid, self.t) < 0.97
        else:
            relevant = 0.3 <= p <= 0.95
        self.log.append({"kind": "action", "action": kind, "objective": oid, "relevant": relevant})


def _tier_for(obj: SimObjective, difficulty: float | None) -> str:
    if difficulty is None:
        return "medium"
    tiers = [t for t in ("easy", "medium", "hard") if obj.items_of(t)]
    return min(tiers, key=lambda t: (abs(obj.items_of(t)[0].label_difficulty - difficulty), t))


def _population_p(learner: SimLearner, item: Any) -> float:
    """Success probability of an average, untrained learner on the item."""
    cfg = learner.config
    guess = cfg.guess_recognition if item.tier == "recognition" else cfg.guess_production
    x = -1.0 - item.true_b
    s = 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))
    return guess + (1.0 - guess - cfg.slip) * s


def _catalog(world: World) -> list[CatalogObjective]:
    return [
        CatalogObjective(
            objective_id=c["objective_id"],
            skill=c["skill"],
            subskill=c["subskill"],
            cefr=c["cefr"],
            difficulty=c["difficulty"],
            prerequisites=tuple(c["prerequisites"]),
        )
        for c in world.catalog()
        if c["skill"] == "grammar"
    ]


# --- policies -----------------------------------------------------------------------


def _run_static(env: Env, cfg: PolicyEvalConfig) -> None:
    grammar = sorted(env.world.grammar(), key=lambda o: (CEFR_ORDER.index(o.cefr), o.objective_id))
    budget = cfg.session_minutes
    start = env.minutes
    recent = env.introduced[-6:]
    for oid in recent[:5]:
        env.review(oid, "recognition")
    current = grammar[min(len(grammar) - 1, env.session // 2)]
    for _ in range(2):
        if env.minutes - start + 5 <= budget:
            env.practice(current.objective_id, None)
    if env.minutes - start + 3 <= budget:
        env.expansion(3)


def _run_adaptive(
    env: Env, cfg: PolicyEvalConfig, pconfig: PlannerConfig, last: dict[str, float]
) -> None:
    vocab = [
        {
            "word": c["word"],
            "card_state": c["card_state"],
            "next_review": c["next_review"],
            "created_at": c["created_at"],
        }
        for c in env.cards.values()
    ]
    new_words = [
        o.subskill
        for o in sorted(env.world.vocabulary(), key=lambda o: o.objective_id)
        if o.objective_id not in env.cards
    ][:3]
    snapshot = LearnerSnapshot(
        user_id=env.learner.learner_id,
        language="Simulated",
        now=env.now(),
        evidence=[visible(r) for r in env.rows],
        vocabulary=vocab,
        catalog=_catalog(env.world),
        goal="conversational",
        target_cefr=cfg.target_cefr,
        last_difficulty=dict(last),
        new_words=new_words,
    )
    result = adaptive_plan(
        snapshot,
        constraints=PlanConstraints(
            time_available_minutes=cfg.session_minutes,
            goal="conversational",
            max_actions=cfg.max_actions,
            avoid_skills=AVOID,
        ),
        config=pconfig,
    )
    by_word = {o.subskill: o.objective_id for o in env.world.vocabulary()}
    for rec in result.recommendations:
        _execute(env, rec, by_word, last)


def _execute(
    env: Env, rec: Recommendation, by_word: dict[str, str], last: dict[str, float]
) -> None:
    predicted = None
    if rec.predicted_success is not None:
        predicted = float(rec.predicted_success.get("p_success", 0.5))
    if rec.activity == "grammar_practice" and rec.objective_id:
        d = rec.difficulty.task_difficulty if rec.difficulty else None
        if d is not None:
            last[rec.objective_id] = d
        env.practice(rec.objective_id, d, predicted=predicted)
    elif rec.activity == "diagnostic_check" and rec.objective_id:
        env.diagnostic(rec.objective_id)
    elif rec.activity == "retention_review" and rec.objective_id:
        env.review(rec.objective_id, "production")
    elif rec.activity == "vocabulary_review":
        oid = by_word.get(rec.target)
        if oid:
            env.review(oid, rec.mode or "recognition")
    elif rec.activity == "vocabulary_remediation":
        oid = by_word.get(rec.target)
        if oid:
            env.remediate_word(oid)
    elif rec.activity == "vocabulary_expansion":
        env.expansion(3)
    elif rec.activity == "conversation_practice":
        env.conversation(env.learner.level)


# --- running and measuring ------------------------------------------------------------


def _grammar_scope(world: World, target: str) -> list[str]:
    limit = CEFR_ORDER.index(target)
    return sorted(o.objective_id for o in world.grammar() if CEFR_ORDER.index(o.cefr) <= limit)


def run_learner(policy: str, index: int, cfg: PolicyEvalConfig) -> dict[str, Any]:
    world = build_world(cfg.world_seed)
    gen = GeneratorConfig(family=cfg.family, gain_peak=cfg.gain_peak)
    lid = f"learner{index:03d}"
    learner = SimLearner.create(lid, world, gen, cfg.seed)
    env = Env(learner, Grader(seed=cfg.seed + index), world, legacy_fsrs=policy != "adaptive_full")
    scope = _grammar_scope(world, cfg.target_cefr)
    start = {o: learner.recall_probability(o, 0.0) for o in scope}
    last: dict[str, float] = {}
    configs = {
        "adaptive": PlannerConfig(
            predictive=False, adaptive_difficulty=False, fsrs_integration=False
        ),
        "adaptive_predictive": PlannerConfig(fsrs_integration=False),
        "adaptive_full": PlannerConfig(),
    }
    days = session_days(cfg.seed, lid, cfg.n_sessions)
    for s, day in enumerate(days):
        env.session, env.t = s, max(env.t, day)
        if policy == "static":
            _run_static(env, cfg)
        else:
            _run_adaptive(env, cfg, configs[policy], last)
    t_end = env.t
    t_delay = t_end + cfg.delay_days
    end = {o: learner.recall_probability(o, t_end) for o in scope}
    delayed = {o: learner.recall_probability(o, t_delay) for o in scope}
    words = env.introduced
    words_end = {o: learner.recall_probability(o, t_end) for o in words}
    words_delayed = {o: learner.recall_probability(o, t_delay) for o in words}
    attempts = [e for e in env.log if e["kind"] == "attempt"]
    grammar_attempts = [e for e in attempts if e["skill"] == "grammar"]
    judged = [e for e in env.log if e["kind"] == "action" and e["relevant"] is not None]
    hours = max(env.minutes, 1.0) / 60.0
    gain = sum(end[o] - start[o] for o in scope)
    retention_vs_end = sum(delayed.values()) / max(sum(end.values()), 1e-9)
    out = {
        "immediate_success": sum(e["success"] for e in attempts) / len(attempts)
        if attempts
        else math.nan,
        "difficulty_adjusted_success": (
            sum(e["success"] - e["pop_p"] for e in grammar_attempts) / len(grammar_attempts)
            if grammar_attempts
            else math.nan
        ),
        "grammar_mastery_gain": gain / len(scope),
        "grammar_recall_end": sum(end.values()) / len(scope),
        "grammar_recall_delayed": sum(delayed.values()) / len(scope),
        "knowledge_retention_ratio": retention_vs_end,
        "objectives_completed_end": sum(v >= 0.8 for v in end.values()) / len(scope),
        "objectives_completed_delayed": sum(v >= 0.8 for v in delayed.values()) / len(scope),
        "words_introduced": float(len(words)),
        "words_recall_delayed": sum(words_delayed.values()) / len(words) if words else math.nan,
        "words_held_delayed": float(sum(v >= 0.8 for v in words_delayed.values())),
        "grammar_gain_per_hour": gain / hours,
        "words_held_per_hour": sum(v >= 0.8 for v in words_delayed.values()) / hours,
        "recommendation_relevance": sum(e["relevant"] for e in judged) / len(judged)
        if judged
        else math.nan,
        "practice_minutes": env.minutes,
    }
    extras = {
        "predictions": env.predictions,
        "retention_pairs": [
            (
                live_retrievability(env.cards[o]["card_state"], T0 + timedelta(days=t_delay)),
                words_delayed[o],
            )
            for o in words
        ],
        "words_end": words_end,
    }
    return {"metrics": out, "extras": extras}


def _paired(a: list[float], b: list[float], *, samples: int, seed: int) -> dict[str, float]:
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if not (math.isnan(x) or math.isnan(y))]
    if not pairs:
        return {"difference": math.nan, "ci_low": math.nan, "ci_high": math.nan}
    diffs = [x - y for x, y in pairs]
    rng = random.Random(seed)
    means = sorted(
        sum(diffs[rng.randrange(len(diffs))] for _ in diffs) / len(diffs) for _ in range(samples)
    )
    return {
        "difference": sum(diffs) / len(diffs),
        "ci_low": means[int(0.025 * (samples - 1))],
        "ci_high": means[int(0.975 * (samples - 1))],
    }


def _mean_ci(values: list[float], *, samples: int, seed: int) -> dict[str, Any]:
    vals = [v for v in values if not math.isnan(v)]
    if not vals:
        return {"mean": math.nan, "ci95": [math.nan, math.nan], "n": 0}
    rng = random.Random(seed)
    means = sorted(
        sum(vals[rng.randrange(len(vals))] for _ in vals) / len(vals) for _ in range(samples)
    )
    return {
        "mean": sum(vals) / len(vals),
        "ci95": [means[int(0.025 * (samples - 1))], means[int(0.975 * (samples - 1))]],
        "n": len(vals),
    }


def _spearman(pairs: list[tuple[float, float]]) -> float:
    if len(pairs) < 3:
        return math.nan

    def ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r

    rx, ry = ranks([p for p, _ in pairs]), ranks([t for _, t in pairs])
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else math.nan


KEY_METRICS = (
    "immediate_success",
    "grammar_recall_delayed",
    "objectives_completed_delayed",
    "words_held_delayed",
    "grammar_gain_per_hour",
    "recommendation_relevance",
)


#: (policy, baseline) pairs isolating one capability each.
ABLATION_STEPS = {
    "adaptive_vs_static": ("adaptive", "static"),
    "prediction_and_difficulty": ("adaptive_predictive", "adaptive"),
    "fsrs_integration_vs_fsrs_only": ("adaptive_full", "adaptive_predictive"),
    "full_vs_static": ("adaptive_full", "static"),
}
ABLATION_METRICS = (
    "immediate_success",
    "grammar_recall_delayed",
    "objectives_completed_delayed",
    "words_introduced",
    "words_recall_delayed",
    "words_held_delayed",
    "words_held_per_hour",
    "grammar_gain_per_hour",
)


def evaluate_policies(cfg: PolicyEvalConfig) -> dict[str, Any]:
    runs: dict[str, list[dict[str, Any]]] = {
        p: [run_learner(p, i, cfg) for i in range(cfg.n_learners)] for p in cfg.policies
    }
    metrics = list(runs[cfg.policies[0]][0]["metrics"])
    results = {
        p: {
            m: _mean_ci(
                [r["metrics"][m] for r in runs[p]], samples=cfg.bootstrap_samples, seed=cfg.seed
            )
            for m in metrics
        }
        for p in cfg.policies
    }
    vs_baseline = {}
    if BASELINE in runs:
        base = runs[BASELINE]
        for p in cfg.policies:
            if p == BASELINE:
                continue
            vs_baseline[p] = {
                m: _paired(
                    [r["metrics"][m] for r in runs[p]],
                    [r["metrics"][m] for r in base],
                    samples=cfg.bootstrap_samples,
                    seed=cfg.seed + 1,
                )
                for m in KEY_METRICS
            }
    # Each capability's own effect: paired differences between ablation steps.
    ablations = {}
    for name, (a, b) in ABLATION_STEPS.items():
        if a in runs and b in runs:
            ablations[name] = {
                m: _paired(
                    [r["metrics"][m] for r in runs[a]],
                    [r["metrics"][m] for r in runs[b]],
                    samples=cfg.bootstrap_samples,
                    seed=cfg.seed + 2,
                )
                for m in ABLATION_METRICS
            }
    prediction = None
    if "adaptive_full" in runs:
        preds = [pair for r in runs["adaptive_full"] for pair in r["extras"]["predictions"]]
        retention = [
            (p, t)
            for r in runs["adaptive_full"]
            for p, t in r["extras"]["retention_pairs"]
            if p is not None
        ]
        prediction = {
            "n": len(preds),
            "auc": auc(preds),
            "log_loss": log_loss(preds),
            "brier": brier(preds),
            "ece": ece(preds),
            "retention": {
                "n": len(retention),
                "mean_predicted": sum(p for p, _ in retention) / len(retention)
                if retention
                else math.nan,
                "mean_true": sum(t for _, t in retention) / len(retention)
                if retention
                else math.nan,
                "spearman": _spearman(retention),
            },
        }
    return {
        "simulated": True,
        "config": asdict(cfg),
        "generator": asdict(GeneratorConfig(family=cfg.family, gain_peak=cfg.gain_peak)),
        "policies": list(cfg.policies),
        "metrics": metrics,
        "key_metrics": list(KEY_METRICS),
        "results": results,
        "baseline": BASELINE,
        "vs_baseline": vs_baseline,
        "ablations": ablations,
        "per_learner": {p: [r["metrics"] for r in runs[p]] for p in cfg.policies},
        "prediction": prediction,
    }
