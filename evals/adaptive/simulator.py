"""Simulated learners — SIMULATION ONLY, never real learner outcomes.

Every number produced from this module is a property of the simulator's
assumptions, not of real learners. The assumptions are explicit, configurable
and documented in ``docs/adaptive-learning.md``. Results must be reported as
simulated.

World
-----
- **Grammar objectives:** ``n_constructions`` constructions over CEFR A1–B2.
  Each has six exercise items: two each at easy, medium and hard tiers.
  - An item's *labelled* difficulty is its construction's CEFR difficulty
    plus a tier offset. That label is what the app sees.
  - Its *true* difficulty adds item-specific noise, which the app never sees.
  - Some constructions have a prerequisite.
- **Vocabulary objectives:** ``n_words`` words, each with a recognition item
  (multiple choice, high guess rate) and a production item.

Learner, ``continuous`` family (default)
----------------------------------------
For objective ``o`` at time ``t``, ability is::

    theta_o(t) = g + u_o - 1 + K_o * (rho + (1 - rho) * exp(-(t - last_o) / S_o))

- ``g`` is general ability and ``u_o`` an objective-specific aptitude.
- ``K_o`` is acquired knowledge, of which a fraction ``rho`` is permanent and
  the rest decays with stability ``S_o``.
- Success on an item of true difficulty ``b`` has probability
  ``guess + (1 - guess - slip) * sigmoid(theta_o - b + e_session)``.
  ``e_session`` is a per-session fluctuation: temporary performance, not
  knowledge.
- **Practice with feedback** raises ``K_o`` by ``eta * h(p) * prereq``.
  - ``p`` is the true success probability of the attempt.
  - ``h`` is the gain profile. By default it peaks at ``p = gain_peak``, the
    *desirable difficulty* assumption. ``gain_peak=None`` makes ``h`` flat,
    so difficulty does not matter.
  - ``prereq`` is reduced while a prerequisite is unknown.
- **Retrieval updates stability:** successful recall after some forgetting
  raises ``S_o`` most (the spacing effect), and failure lowers it.
- **Exposure** without retrieval adds a little knowledge and no stability.

Learner, ``bkt`` family
-----------------------
Discrete knowledge per objective, with learn, forget, slip and guess
probabilities, and no effect of item difficulty. It exists so that model
comparisons are not judged only on a generator that resembles one candidate.

Randomness uses common random numbers. Outcome draws are seeded by
``(learner, objective, attempt number)``, and session fluctuations by
``(learner, session index)``. Different policies therefore face the same luck
wherever their histories coincide.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from src.evidence.difficulty import CEFR_ORDER, cefr_to_difficulty

T0 = datetime(2026, 1, 1, tzinfo=UTC)
SIM_LANGUAGE = "Simulated"
#: Tier offsets on the labelled difficulty scale.
TIER_OFFSETS = {"easy": -0.1, "medium": 0.0, "hard": 0.1}
_DIFFICULTY_SCALE = 4.0


def sim_time(days: float) -> str:
    """ISO timestamp ``days`` after the simulation epoch."""
    return (T0 + timedelta(days=days)).isoformat()


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _uniform(*key: object) -> float:
    """A deterministic uniform draw for a key (common random numbers)."""
    return random.Random(":".join(str(k) for k in key)).random()


def _gauss(*key: object, sd: float = 1.0) -> float:
    return random.Random(":".join(str(k) for k in key)).gauss(0.0, sd)


@dataclass(frozen=True)
class SimItem:
    item_id: str
    objective_id: str
    tier: str  # easy | medium | hard | recognition | production
    label_difficulty: float  # what the app sees, in [0, 1]
    true_b: float  # hidden, logits


@dataclass(frozen=True)
class SimObjective:
    objective_id: str
    skill: str  # grammar | vocabulary
    subskill: str  # construction id, or the word
    cefr: str
    prerequisites: tuple[str, ...]
    items: tuple[SimItem, ...]

    def item(self, tier: str) -> SimItem:
        """The first item of a tier (deterministic)."""
        return next(i for i in self.items if i.tier == tier)

    def items_of(self, tier: str) -> list[SimItem]:
        return [i for i in self.items if i.tier == tier]


@dataclass(frozen=True)
class World:
    objectives: dict[str, SimObjective]

    def grammar(self) -> list[SimObjective]:
        return [o for o in self.objectives.values() if o.skill == "grammar"]

    def vocabulary(self) -> list[SimObjective]:
        return [o for o in self.objectives.values() if o.skill == "vocabulary"]

    def catalog(self) -> list[dict[str, Any]]:
        """The app-visible catalog: no hidden difficulties."""
        return [
            {
                "objective_id": o.objective_id,
                "skill": o.skill,
                "subskill": o.subskill,
                "cefr": o.cefr,
                "difficulty": cefr_to_difficulty(o.cefr),
                "prerequisites": list(o.prerequisites),
            }
            for o in sorted(self.objectives.values(), key=lambda o: o.objective_id)
        ]


def build_world(seed: int = 7, *, n_constructions: int = 12, n_words: int = 40) -> World:
    """Build a deterministic world of grammar and vocabulary objectives."""
    levels = CEFR_ORDER[:4]
    objectives: dict[str, SimObjective] = {}
    grammar_ids: list[str] = []
    for i in range(n_constructions):
        cefr = levels[min(3, i * 4 // n_constructions)]
        cid = f"construction_{i + 1:02d}"
        oid = f"grammar.{cid}"
        base = cefr_to_difficulty(cefr) or 0.5
        items = []
        for tier, offset in TIER_OFFSETS.items():
            for k in range(2):
                label = max(0.0, min(1.0, base + offset))
                noise = _gauss(seed, "item", cid, tier, k, sd=0.4)
                items.append(
                    SimItem(
                        item_id=f"{cid}#{tier}{k}",
                        objective_id=oid,
                        tier=tier,
                        label_difficulty=round(label, 4),
                        true_b=_DIFFICULTY_SCALE * (label - 0.5) + noise,
                    )
                )
        # A construction above A1 depends on one earlier construction ~half the time.
        prereqs: tuple[str, ...] = ()
        earlier = [g for g in grammar_ids if g < oid]
        if earlier and cefr != "A1" and _uniform(seed, "prereq", cid) < 0.6:
            prereqs = (earlier[int(_uniform(seed, "pick", cid) * len(earlier))],)
        grammar_ids.append(oid)
        objectives[oid] = SimObjective(oid, "grammar", cid, cefr, prereqs, tuple(items))
    for i in range(n_words):
        cefr = levels[min(3, i * 4 // n_words)]
        word = f"word_{i + 1:02d}"
        oid = f"vocabulary.{word}"
        base = cefr_to_difficulty(cefr) or 0.5
        noise = _gauss(seed, "word", word, sd=0.5)
        b = _DIFFICULTY_SCALE * (base - 0.5) + noise
        items_v = (
            SimItem(f"{word}#recognition", oid, "recognition", base, b - 1.2),
            SimItem(f"{word}#production", oid, "production", base, b + 0.3),
        )
        objectives[oid] = SimObjective(oid, "vocabulary", word, cefr, (), items_v)
    return World(objectives)


@dataclass(frozen=True)
class GeneratorConfig:
    """Ground-truth assumptions. Change these to test robustness."""

    family: str = "continuous"  # continuous | bkt
    #: Success probability at which practice teaches most (None = flat gain).
    gain_peak: float | None = 0.7
    gain_width: float = 0.3
    learning_rate: float = 0.45
    retained_fraction: float = 0.4
    initial_stability_days: float = 2.0
    session_sd: float = 0.4
    slip: float = 0.05
    guess_production: float = 0.02
    guess_recognition: float = 0.25
    #: Learning multiplier while a prerequisite is unknown.
    prerequisite_penalty: float = 0.4
    #: Learning multiplier for attempts graded without feedback (diagnostics).
    no_feedback_factor: float = 0.3
    exposure_gain: float = 0.12
    # bkt family
    bkt_learn: float = 0.15
    bkt_forget_per_day: float = 0.01

    def gain(self, p: float) -> float:
        if self.gain_peak is None:
            return 0.7
        return math.exp(-(((p - self.gain_peak) / self.gain_width) ** 2))


@dataclass
class _Memory:
    knowledge: float = 0.0
    stability: float = 2.0
    last_t: float | None = None
    attempts: int = 0
    known: bool = False  # bkt family


@dataclass
class SimLearner:
    """One simulated learner with hidden ground truth."""

    learner_id: str
    world: World
    config: GeneratorConfig
    seed: int
    general: float = 0.0
    level: int = 0
    learning_rate: float = 0.45
    memory: dict[str, _Memory] = field(default_factory=dict)
    aptitude: dict[str, float] = field(default_factory=dict)

    @classmethod
    def create(
        cls, learner_id: str, world: World, config: GeneratorConfig, seed: int
    ) -> SimLearner:
        lr = config.learning_rate * math.exp(_gauss(seed, learner_id, "lr", sd=0.3))
        learner = cls(
            learner_id=learner_id,
            world=world,
            config=config,
            seed=seed,
            general=_gauss(seed, learner_id, "g", sd=0.8),
            level=int(_uniform(seed, learner_id, "level") * 3),  # 0..2: A1, A2, B1 known below
            learning_rate=lr,
        )
        for oid, obj in world.objectives.items():
            learner.aptitude[oid] = _gauss(seed, learner_id, "u", oid, sd=0.6)
            m = _Memory(stability=config.initial_stability_days)
            if CEFR_ORDER.index(obj.cefr) < learner.level:
                # Prior knowledge: learned long ago, consolidated.
                m.knowledge, m.stability, m.last_t, m.known = 2.0, 40.0, -30.0, True
            elif config.family == "bkt" and _uniform(seed, learner_id, "init", oid) < 0.1:
                m.known = True
            learner.memory[oid] = m
        return learner

    # --- ground truth -------------------------------------------------------

    def _retention(self, m: _Memory, t: float) -> float:
        if m.last_t is None:
            return 1.0
        return math.exp(-max(0.0, t - m.last_t) / max(m.stability, 0.1))

    def ability(self, objective_id: str, t: float) -> float:
        m = self.memory[objective_id]
        rho = self.config.retained_fraction
        held = m.knowledge * (rho + (1.0 - rho) * self._retention(m, t))
        return self.general + self.aptitude[objective_id] - 1.0 + held

    def _guess(self, item: SimItem) -> float:
        cfg = self.config
        return cfg.guess_recognition if item.tier == "recognition" else cfg.guess_production

    def p_success(self, item: SimItem, t: float, session_offset: float = 0.0) -> float:
        """True success probability (hidden from the app)."""
        cfg = self.config
        guess = self._guess(item)
        if cfg.family == "bkt":
            m = self.memory[item.objective_id]
            # Forgetting: a known state decays per day since last practice.
            known = m.known
            p_known = 1.0
            if known and m.last_t is not None:
                p_known = (1.0 - cfg.bkt_forget_per_day) ** max(0.0, t - m.last_t)
            p_k = p_known if known else 0.0
            return p_k * (1.0 - cfg.slip) + (1.0 - p_k) * guess
        theta = self.ability(item.objective_id, t) + session_offset
        return guess + (1.0 - guess - cfg.slip) * _sigmoid(theta - item.true_b)

    def session_offset(self, session_index: int) -> float:
        return _gauss(
            self.seed, self.learner_id, "session", session_index, sd=self.config.session_sd
        )

    def _prereq_factor(self, objective_id: str, t: float) -> float:
        obj = self.world.objectives[objective_id]
        for pre in obj.prerequisites:
            if self.config.family == "bkt":
                if not self.memory[pre].known:
                    return self.config.prerequisite_penalty
            elif self.ability(pre, t) < 0.0:
                return self.config.prerequisite_penalty
        return 1.0

    def attempt(
        self, item: SimItem, t: float, session_index: int, *, feedback: bool = True
    ) -> tuple[bool, float]:
        """Attempt an item: draw the outcome, then learn. Returns (success, p)."""
        cfg = self.config
        m = self.memory[item.objective_id]
        offset = 0.0 if cfg.family == "bkt" else self.session_offset(session_index)
        p = self.p_success(item, t, offset)
        m.attempts += 1
        success = _uniform(self.seed, self.learner_id, item.objective_id, m.attempts) < p
        factor = 1.0 if feedback else cfg.no_feedback_factor
        prereq = self._prereq_factor(item.objective_id, t)
        if cfg.family == "bkt":
            if m.known and m.last_t is not None:
                keep = (1.0 - cfg.bkt_forget_per_day) ** max(0.0, t - m.last_t)
                m.known = (
                    _uniform(self.seed, self.learner_id, "keep", item.objective_id, m.attempts)
                    < keep
                )
            if not m.known:
                learn = cfg.bkt_learn * factor * prereq
                m.known = (
                    _uniform(self.seed, self.learner_id, "learn", item.objective_id, m.attempts)
                    < learn
                )
            m.last_t = t
            return success, p
        r = self._retention(m, t)
        # Stability: the spacing effect on successful retrieval, decay on failure.
        if m.last_t is not None and m.knowledge > 0.0:
            if success:
                m.stability = m.stability * (1.0 + 1.5 * (1.0 - r)) + 0.5
            else:
                m.stability = max(1.0, 0.7 * m.stability)
        # Knowledge: the decayed part is consolidated at its current level,
        # then practice adds to it.
        rho = cfg.retained_fraction
        m.knowledge = m.knowledge * (rho + (1.0 - rho) * r)
        p_clean = self.p_success(item, t, 0.0)
        m.knowledge = min(
            4.0, m.knowledge + self.learning_rate * cfg.gain(p_clean) * factor * prereq
        )
        m.last_t = t
        return success, p

    def expose(self, objective_id: str, t: float) -> None:
        """Meet an item without retrieval (e.g. a word in the tutor's reply)."""
        cfg = self.config
        m = self.memory[objective_id]
        if cfg.family == "bkt":
            if not m.known:
                m.known = (
                    _uniform(self.seed, self.learner_id, "expose", objective_id, t)
                    < cfg.bkt_learn * 0.3
                )
            m.last_t = t if m.last_t is None else m.last_t
            return
        r = self._retention(m, t)
        rho = cfg.retained_fraction
        m.knowledge = min(4.0, m.knowledge * (rho + (1.0 - rho) * r) + cfg.exposure_gain)
        m.last_t = t

    def recall_probability(self, objective_id: str, t: float) -> float:
        """True success probability on the objective's reference item at ``t``
        (medium tier for grammar, production for vocabulary), no fluctuation."""
        obj = self.world.objectives[objective_id]
        tier = "medium" if obj.skill == "grammar" else "production"
        return self.p_success(obj.item(tier), t, 0.0)


# --- Evidence rows ----------------------------------------------------------


@dataclass
class Grader:
    """Turns attempts into production-format evidence rows, with grading noise.

    Rows carry hidden ``_truth`` and ``_p_true`` keys for evaluation only.
    :func:`visible` strips them before anything is given to a model.
    """

    seed: int
    double_grading_rate: float = 0.25
    counter: int = 0

    def _flip(self, key: tuple[object, ...], reliability: float) -> bool:
        return _uniform(self.seed, "flip", *key) < (1.0 - reliability) * 0.5

    def graded(
        self,
        learner_id: str,
        obj: SimObjective,
        item: SimItem,
        success: bool,
        p_true: float,
        t: float,
        session_id: str,
        *,
        task_type: str,
        reliability: float,
        item_level: bool = True,
    ) -> list[dict[str, Any]]:
        self.counter += 1
        n = self.counter
        rows = []
        graders = 1
        if task_type == "conversation" and _uniform(self.seed, "double", learner_id, n) < (
            self.double_grading_rate
        ):
            graders = 2
        correlation = f"{learner_id}-c{n}"
        for g in range(graders):
            observed = success
            if self._flip((learner_id, n, g), reliability):
                observed = not observed
            if obj.skill == "grammar":
                event_type = "GRAMMAR_SUCCESS" if observed else "GRAMMAR_ERROR"
                subskill = obj.subskill
                item_id = item.item_id if item_level else obj.subskill
                objective_id = obj.objective_id
            else:
                event_type = "REVIEW_RESULT"
                subskill = item.tier  # recognition | production, as the app records it
                item_id = obj.subskill
                objective_id = f"vocabulary.{item.tier}"
            rows.append(
                {
                    "event_id": f"{learner_id}-e{n}-{g}",
                    "event_type": event_type,
                    "user_id": learner_id,
                    "language": SIM_LANGUAGE,
                    "skill": obj.skill,
                    "subskill": subskill,
                    "objective_id": objective_id,
                    "item_id": item_id,
                    "assessment": "correct" if observed else "incorrect",
                    "confidence": reliability,
                    "task_type": task_type,
                    "difficulty": item.label_difficulty,
                    "difficulty_basis": "cefr_label",
                    "session_id": session_id,
                    "correlation_id": correlation if graders > 1 else None,
                    "source": f"simulator-{g}",
                    "created_at": sim_time(t + g * 1e-6),
                    "payload": {"tier": item.tier, "sim_objective": obj.objective_id},
                    "_truth": success,
                    "_p_true": p_true,
                    "_target": g == 0,
                }
            )
        return rows

    def exposure(
        self, learner_id: str, obj: SimObjective, t: float, session_id: str
    ) -> dict[str, Any]:
        self.counter += 1
        return {
            "event_id": f"{learner_id}-e{self.counter}-x",
            "event_type": "VOCAB_OBSERVED",
            "user_id": learner_id,
            "language": SIM_LANGUAGE,
            "skill": obj.skill,
            "subskill": "exposure",
            "objective_id": obj.objective_id,
            "item_id": obj.subskill,
            "assessment": "exposed",
            "confidence": 1.0,
            "task_type": "conversation",
            "difficulty": None,
            "difficulty_basis": "unknown",
            "session_id": session_id,
            "source": "simulator",
            "created_at": sim_time(t),
            "payload": {"sim_objective": obj.objective_id},
            "_target": False,
        }


def visible(row: dict[str, Any]) -> dict[str, Any]:
    """The row as the app would store it: hidden ground-truth keys removed."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def session_days(seed: int, learner_id: str, n_sessions: int) -> list[float]:
    """Session start times (days): gaps of 1–3 days, deterministic per learner."""
    t, days = 0.0, []
    for s in range(n_sessions):
        days.append(t)
        t += 1.0 + int(_uniform(seed, learner_id, "gap", s) * 3)
    return days


def random_practice_log(
    learner: SimLearner,
    grader: Grader,
    *,
    n_sessions: int = 12,
    attempts_per_session: int = 10,
) -> list[dict[str, Any]]:
    """Interaction log under a random practice policy (for model evaluation).

    Each session practises constructions near the learner's level, on random
    tiers, mostly as graded exercises and partly in conversation (construction
    level item ids, lower reliability, sometimes double-graded).
    """
    world, lid, seed = learner.world, learner.learner_id, learner.seed
    grammar = sorted(world.grammar(), key=lambda o: o.objective_id)
    rows: list[dict[str, Any]] = []
    for s, day in enumerate(session_days(seed, lid, n_sessions)):
        sid = f"{lid}-s{s}"
        band = [o for o in grammar if abs(CEFR_ORDER.index(o.cefr) - learner.level) <= 1] or grammar
        for a in range(attempts_per_session):
            t = day + a * 0.002
            obj = band[int(_uniform(seed, lid, "obj", s, a) * len(band))]
            tier = ("easy", "medium", "hard")[int(_uniform(seed, lid, "tier", s, a) * 3)]
            items = obj.items_of(tier)
            item = items[int(_uniform(seed, lid, "item", s, a) * len(items))]
            conversation = _uniform(seed, lid, "conv", s, a) < 0.3
            success, p = learner.attempt(item, t, s)
            rows += grader.graded(
                lid,
                obj,
                item,
                success,
                p,
                t,
                sid,
                task_type="conversation" if conversation else "exercise",
                reliability=0.75 if conversation else 0.95,
                item_level=not conversation,
            )
    return rows
