"""The adaptive evaluation harness: simulator, model comparison, policy simulation."""

from __future__ import annotations

from typing import Any

from evals.adaptive import candidates, model_eval, policy_eval
from evals.adaptive.report import BANNER, render_models, render_policies
from evals.adaptive.simulator import (
    GeneratorConfig,
    Grader,
    SimLearner,
    build_world,
    random_practice_log,
    visible,
)


def _log(seed: int = 1, family: str = "continuous") -> list[dict[str, Any]]:
    world = build_world(7)
    learner = SimLearner.create("l0", world, GeneratorConfig(family=family), seed)
    return random_practice_log(learner, Grader(seed=seed), n_sessions=3, attempts_per_session=5)


class TestSimulator:
    def test_deterministic(self):
        assert _log() == _log()
        assert _log(1) != _log(2)

    def test_visible_rows_hide_ground_truth(self):
        for row in _log():
            assert "_truth" in row or row.get("_target") is False
            assert not any(k.startswith("_") for k in visible(row))

    def test_practice_with_feedback_raises_true_recall(self):
        world = build_world(7)
        learner = SimLearner.create("l1", world, GeneratorConfig(), 3)
        obj = next(o for o in world.grammar() if o.cefr == "B2")
        before = learner.recall_probability(obj.objective_id, 0.0)
        for k in range(10):
            learner.attempt(obj.item("easy"), 0.01 * k, 0)
        assert learner.recall_probability(obj.objective_id, 0.2) > before

    def test_bkt_family_runs(self):
        assert _log(family="bkt")


class _Spy:
    """A candidate that records the call order to prove predict-before-observe."""

    name = "spy"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fit(self, train_logs: list[list[dict[str, Any]]]) -> None:
        return None

    def learner(self) -> Any:
        spy = self

        class P:
            def predict(self, row: dict[str, Any]) -> float:
                assert not any(k.startswith("_") for k in row)  # no hidden truth
                spy.calls.append(("predict", row["event_id"]))
                return 0.5

            def observe(self, row: dict[str, Any]) -> None:
                spy.calls.append(("observe", row["event_id"]))

        return P()


class TestModelEval:
    def test_predictions_precede_observations(self):
        spy = _Spy()
        model_eval.run_candidate(spy, [_log()])
        seen: set[str] = set()
        for kind, event_id in spy.calls:
            if kind == "predict":
                assert event_id not in seen
            else:
                seen.add(event_id)

    def test_metrics(self):
        assert model_eval.auc([(0.9, 1.0), (0.1, 0.0)]) == 1.0
        assert model_eval.auc([(0.1, 1.0), (0.9, 0.0)]) == 0.0
        assert abs(model_eval.brier([(1.0, 1.0), (0.0, 0.0)])) < 1e-12
        assert model_eval.ece([(0.5, 1.0), (0.5, 0.0)]) == 0.0

    def test_small_comparison_runs_and_is_labelled(self):
        cfg = model_eval.ModelEvalConfig(n_train=3, n_test=3, n_sessions=3, bootstrap_samples=20)
        data = model_eval.evaluate(cfg)
        assert data["simulated"] is True
        names = set(data["regimes"]["cold"])
        assert names == {"legacy_incremental", "lkm_v2_rasch", "bkt", "elo", "lkm_subskill_v1"}
        assert "vs_baseline" in data["regimes"]["warm"]["bkt"]
        assert BANNER in render_models(data)

    def test_bkt_update_is_bayesian(self):
        p = candidates.BKTParams(p_init=0.5, p_learn=0.0, p_slip=0.1, p_guess=0.2)
        assert p.update(0.5, 1.0) > 0.5 > p.update(0.5, 0.0)


class TestPolicyEval:
    def test_small_run_compares_all_policies(self):
        cfg = policy_eval.PolicyEvalConfig(n_learners=2, n_sessions=4, bootstrap_samples=20)
        data = policy_eval.evaluate_policies(cfg)
        assert data["simulated"] is True
        assert set(data["results"]) == set(policy_eval.POLICIES)
        assert set(data["vs_existing"]) == set(policy_eval.POLICIES) - {"existing_planner"}
        for res in data["results"].values():
            assert 0.0 <= res["immediate_success"]["mean"] <= 1.0
            assert 0.0 <= res["grammar_recall_delayed"]["mean"] <= 1.0
        md = render_policies(data)
        assert BANNER in md and "delayed" in md

    def test_existing_planner_patch_is_scoped(self):
        import src.curriculum.planner as legacy

        before = legacy.vocabulary_db
        policy_eval.run_learner("existing_planner", 0, policy_eval.PolicyEvalConfig(n_sessions=2))
        assert legacy.vocabulary_db is before


class TestRealLogs:
    def test_real_evidence_path_uses_observed_outcomes(self):
        from evals.adaptive.report import REAL_BANNER

        rows = []
        for seed in range(6):
            world = build_world(7)
            learner = SimLearner.create(f"user{seed}", world, GeneratorConfig(), seed)
            log = random_practice_log(
                learner, Grader(seed=seed), n_sessions=2, attempts_per_session=4
            )
            rows += [visible(r) for r in log]  # as the app would store them
        train, test = model_eval.split_real_logs(rows)
        users = {log[0]["user_id"] for log in train} | {log[0]["user_id"] for log in test}
        assert len(users) == 6 and not (
            {log[0]["user_id"] for log in train} & {log[0]["user_id"] for log in test}
        )
        data = model_eval.compare(
            train, test, simulated=False, meta={"source": "t"}, samples=10, seed=1
        )
        assert data["simulated"] is False and data["n_test_predictions"] > 0
        assert "uncertainty" not in data["regimes"]["cold"]["lkm_subskill_v1"]
        md = render_models(data)
        assert REAL_BANNER in md and BANNER not in md
