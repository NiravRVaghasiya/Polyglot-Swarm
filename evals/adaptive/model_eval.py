"""Held-out learner-model comparison (Checkpoint 1) — SIMULATED learners.

Protocol:

- **Learner split.** Training and test learners are disjoint. Simulated logs
  are generated under a random practice policy. ``fit`` sees only training
  logs; metrics are computed only on test learners.
- **No future leakage.** For each test learner, rows are fed in time order;
  ``predict(row)`` is called before ``observe(row)``.
- **Target.** The learner's *true* outcome on a graded grammar attempt
  (hidden ``_truth``), not the noisy grade the model sees. One target per
  attempt: the second grader of a double-graded attempt is evidence, never a
  second target.
- **Regimes.**
  - ``cold``: no training data is used — literature BKT defaults, Elo item
    difficulties at their labels, default subskill config. This is the app
    today, which has no learner data.
  - ``warm``: parameters are fitted on the training learners.
- **Metrics.** AUC, log loss, Brier score and 10-bin ECE.
  - 95% intervals come from a learner-level bootstrap.
  - Paired differences against the ``lkm_v2_rasch`` baseline use the same
    bootstrap.
  - Results are also broken down by how much prior evidence the subskill had.
  - For the subskill model, the share of true success probabilities inside
    its 95% prediction interval is reported (uncertainty honesty).
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass
from typing import Any

from evals.adaptive.candidates import Candidate, all_candidates, outcome
from evals.adaptive.simulator import (
    GeneratorConfig,
    Grader,
    SimLearner,
    build_world,
    random_practice_log,
    visible,
)

BASELINE = "lkm_v2_rasch"


@dataclass(frozen=True)
class ModelEvalConfig:
    family: str = "continuous"
    n_train: int = 40
    n_test: int = 60
    n_sessions: int = 12
    attempts_per_session: int = 10
    world_seed: int = 7
    seed: int = 20261107
    bootstrap_samples: int = 1000


def generate_logs(cfg: ModelEvalConfig, *, prefix: str, count: int) -> list[list[dict[str, Any]]]:
    world = build_world(cfg.world_seed)
    gen = GeneratorConfig(family=cfg.family)
    logs = []
    for i in range(count):
        learner = SimLearner.create(f"{prefix}{i:03d}", world, gen, cfg.seed)
        grader = Grader(seed=cfg.seed + i)
        logs.append(
            random_practice_log(
                learner,
                grader,
                n_sessions=cfg.n_sessions,
                attempts_per_session=cfg.attempts_per_session,
            )
        )
    return logs


# --- metrics -----------------------------------------------------------------

Pair = tuple[float, float]  # (prediction, true outcome 0/1)


def auc(pairs: list[Pair]) -> float:
    """Area under the ROC curve (Mann–Whitney with mid-ranks)."""
    pos = sum(1 for _, y in pairs if y >= 0.5)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return math.nan
    ordered = sorted(pairs, key=lambda t: t[0])
    rank_sum, i = 0.0, 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][0] == ordered[i][0]:
            j += 1
        mid = (i + j) / 2.0 + 1.0
        rank_sum += mid * sum(1 for k in range(i, j + 1) if ordered[k][1] >= 0.5)
        i = j + 1
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def log_loss(pairs: list[Pair]) -> float:
    if not pairs:
        return math.nan
    total = 0.0
    for p, y in pairs:
        p = min(1 - 1e-6, max(1e-6, p))
        total -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return total / len(pairs)


def brier(pairs: list[Pair]) -> float:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else math.nan


def ece(pairs: list[Pair], bins: int = 10) -> float:
    if not pairs:
        return math.nan
    buckets: list[list[Pair]] = [[] for _ in range(bins)]
    for p, y in pairs:
        buckets[min(bins - 1, int(p * bins))].append((p, y))
    total = len(pairs)
    return sum(
        len(b) / total * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b))
        for b in buckets
        if b
    )


METRICS = {"auc": auc, "log_loss": log_loss, "brier": brier, "ece": ece}


def _bootstrap(
    per_learner: list[list[Pair]], fn: Any, *, samples: int, seed: int
) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(per_learner)
    values = []
    for _ in range(samples):
        pooled = [pair for _ in range(n) for pair in per_learner[rng.randrange(n)]]
        v = fn(pooled)
        if not math.isnan(v):
            values.append(v)
    if not values:
        return (math.nan, math.nan)
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]


def _paired_bootstrap(
    a: list[list[Pair]], b: list[list[Pair]], fn: Any, *, samples: int, seed: int
) -> tuple[float, float, float]:
    """Point estimate and 95% interval of fn(a) - fn(b), resampling learners."""
    point = fn([x for xs in a for x in xs]) - fn([x for xs in b for x in xs])
    rng = random.Random(seed)
    n = len(a)
    values = []
    for _ in range(samples):
        idx = [rng.randrange(n) for _ in range(n)]
        va = fn([x for i in idx for x in a[i]])
        vb = fn([x for i in idx for x in b[i]])
        if not (math.isnan(va) or math.isnan(vb)):
            values.append(va - vb)
    values.sort()
    lo = values[int(0.025 * (len(values) - 1))] if values else math.nan
    hi = values[int(0.975 * (len(values) - 1))] if values else math.nan
    return point, lo, hi


def _bucket(n_prior: int) -> str:
    if n_prior == 0:
        return "0"
    return "1-3" if n_prior <= 3 else "4+"


def run_candidate(
    cand: Candidate, test_logs: list[list[dict[str, Any]]]
) -> tuple[list[list[Pair]], dict[str, list[Pair]], dict[str, float] | None]:
    """Online predictions for every test learner (predict before observe)."""
    per_learner: list[list[Pair]] = []
    by_bucket: dict[str, list[Pair]] = {"0": [], "1-3": [], "4+": []}
    covered = total = 0
    width_sum = 0.0
    for log in test_logs:
        predictor = cand.learner()
        pairs: list[Pair] = []
        prior: dict[str, int] = {}
        groups: set[str] = set()
        for row in log:
            seen_row = visible(row)
            corr = row.get("correlation_id")
            # Simulated rows say which row is the target; real rows use the
            # first row of each correlated group.
            target = row.get("_target", not corr or corr not in groups)
            if corr:
                groups.add(str(corr))
            observed = outcome(row)
            if target and row.get("skill") == "grammar" and observed is not None:
                p = predictor.predict(seen_row)
                # Simulated: the hidden true outcome. Real: the graded outcome.
                y = (1.0 if row["_truth"] else 0.0) if "_truth" in row else observed
                pairs.append((p, y))
                key = str(row.get("subskill"))
                by_bucket[_bucket(prior.get(key, 0))].append((p, y))
                prior[key] = prior.get(key, 0) + 1
                interval = getattr(predictor, "interval", None)
                if interval is not None and "_p_true" in row:
                    _, lo, hi = interval(seen_row)
                    total += 1
                    covered += int(lo <= float(row["_p_true"]) <= hi)
                    width_sum += hi - lo
            predictor.observe(seen_row)
        per_learner.append(pairs)
    coverage = (
        {"interval_coverage": covered / total, "mean_interval_width": width_sum / total}
        if total
        else None
    )
    return per_learner, by_bucket, coverage


def split_real_logs(
    rows: list[dict[str, Any]], *, train_fraction: float = 0.4
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]]]:
    """Group real evidence rows by learner (time-ordered); split learners by hash.

    The split is by learner, so no learner's evidence is in both sets.
    """
    by_user: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_user.setdefault(str(row.get("user_id")), []).append(row)
    train: list[list[dict[str, Any]]] = []
    test: list[list[dict[str, Any]]] = []
    for user, user_rows in sorted(by_user.items()):
        ordered = sorted(
            user_rows, key=lambda r: (str(r.get("created_at")), str(r.get("event_id")))
        )
        bucket = int(hashlib.sha256(f"adaptive-split-v1:{user}".encode()).hexdigest()[:8], 16)
        (train if bucket / 2**32 < train_fraction else test).append(ordered)
    return train, test


def evaluate(cfg: ModelEvalConfig) -> dict[str, Any]:
    train = [
        [visible(r) for r in log] for log in generate_logs(cfg, prefix="train", count=cfg.n_train)
    ]
    test = generate_logs(cfg, prefix="test", count=cfg.n_test)
    meta = {"config": asdict(cfg), "generator": asdict(GeneratorConfig(family=cfg.family))}
    return compare(
        train, test, simulated=True, meta=meta, samples=cfg.bootstrap_samples, seed=cfg.seed
    )


def compare(
    train: list[list[dict[str, Any]]],
    test: list[list[dict[str, Any]]],
    *,
    simulated: bool,
    meta: dict[str, Any],
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """Run every candidate, cold and warm, on held-out test logs."""
    out: dict[str, Any] = {
        "simulated": simulated,
        **meta,
        "n_train_learners": len(train),
        "n_test_learners": len(test),
        "regimes": {},
    }
    for regime in ("cold", "warm"):
        results: dict[str, Any] = {}
        preds: dict[str, list[list[Pair]]] = {}
        for cand in all_candidates(warm=regime == "warm"):
            cand.fit(train if regime == "warm" else [])
            per_learner, by_bucket, coverage = run_candidate(cand, test)
            preds[cand.name] = per_learner
            pooled = [p for xs in per_learner for p in xs]
            entry: dict[str, Any] = {"n": len(pooled)}
            for m, fn in METRICS.items():
                lo, hi = _bootstrap(per_learner, fn, samples=samples, seed=seed + len(m))
                entry[m] = {"value": fn(pooled), "ci95": [lo, hi]}
            entry["by_prior_evidence"] = {
                b: {"n": len(v), "auc": auc(v), "log_loss": log_loss(v)}
                for b, v in by_bucket.items()
            }
            if coverage is not None:
                entry["uncertainty"] = coverage
            tuning = getattr(cand, "tuning_log", None)
            if tuning:
                entry["tuning"] = tuning
                entry["selected_config"] = asdict(getattr(cand, "config"))  # noqa: B009
            results[cand.name] = entry
        for name, per_learner in preds.items():
            if name == BASELINE:
                continue
            results[name]["vs_baseline"] = {
                m: dict(
                    zip(
                        ("difference", "ci_low", "ci_high"),
                        _paired_bootstrap(
                            per_learner,
                            preds[BASELINE],
                            METRICS[m],
                            samples=samples,
                            seed=seed + 99,
                        ),
                        strict=True,
                    )
                )
                for m in ("auc", "log_loss")
            }
        if "lkm_subskill_v1" in preds and "elo" in preds:
            results["lkm_subskill_v1"]["vs_elo"] = {
                m: dict(
                    zip(
                        ("difference", "ci_low", "ci_high"),
                        _paired_bootstrap(
                            preds["lkm_subskill_v1"],
                            preds["elo"],
                            METRICS[m],
                            samples=samples,
                            seed=seed + 98,
                        ),
                        strict=True,
                    )
                )
                for m in ("auc", "log_loss", "ece")
            }
        out["regimes"][regime] = results
    out["n_test_predictions"] = out["regimes"]["cold"][BASELINE]["n"]
    return out
