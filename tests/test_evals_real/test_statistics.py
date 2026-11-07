"""Statistical primitives behind the real-model evaluation, checked against
known reference values."""

from __future__ import annotations

import math
import random

import pytest

from src.evaluation.calibration import calibration_error
from src.evaluation.statistics import (
    area_under_risk_coverage,
    bootstrap_ci,
    brier_score,
    cohens_kappa,
    fit_histogram_binning,
    fit_platt,
    gate_decision,
    mcnemar_exact,
    risk_coverage,
    wilson_interval,
)


class TestWilson:
    def test_reference_value(self):
        # 8/10: Wilson 95% interval is (0.4902, 0.9433).
        lo, hi = wilson_interval(8, 10)
        assert lo == pytest.approx(0.4902, abs=1e-3)
        assert hi == pytest.approx(0.9433, abs=1e-3)

    def test_extremes_stay_in_range(self):
        assert wilson_interval(0, 5)[0] == 0.0
        assert wilson_interval(5, 5)[1] == 1.0
        assert wilson_interval(0, 5)[1] > 0.0  # not a degenerate [0, 0]

    def test_empty_is_uninformative(self):
        assert wilson_interval(0, 0) == (0.0, 1.0)


class TestMcNemar:
    def test_reference_values(self):
        assert mcnemar_exact(0, 6) == pytest.approx(0.03125)  # 2 * 0.5**6
        assert mcnemar_exact(1, 1) == 1.0
        assert mcnemar_exact(0, 0) == 1.0
        assert mcnemar_exact(2, 8) == pytest.approx(0.109375)

    def test_symmetric(self):
        assert mcnemar_exact(3, 9) == mcnemar_exact(9, 3)


class TestAgreementAndScores:
    def test_kappa_reference(self):
        # Observed agreement 0.7; expected 0.7*0.6 + 0.3*0.4 = 0.54 -> kappa 0.3478.
        a = [1] * 25 + [1] * 10 + [0] * 5 + [0] * 10
        b = [1] * 25 + [0] * 10 + [1] * 5 + [0] * 10
        assert cohens_kappa(a, b) == pytest.approx(0.3478, abs=1e-3)

    def test_kappa_perfect_and_unequal(self):
        assert cohens_kappa([1, 0, 1], [1, 0, 1]) == 1.0
        with pytest.raises(ValueError):
            cohens_kappa([1], [1, 0])

    def test_brier(self):
        assert brier_score([(1.0, True), (0.0, False)]) == 0.0
        assert brier_score([(0.8, False)]) == pytest.approx(0.64)
        assert math.isnan(brier_score([]))

    def test_risk_coverage_and_aurc(self):
        good = [(0.9, True), (0.8, True), (0.2, False)]
        bad = [(0.9, False), (0.8, True), (0.2, True)]
        assert risk_coverage(good)[0] == (pytest.approx(1 / 3), 1.0)
        assert area_under_risk_coverage(good) < area_under_risk_coverage(bad)

    def test_bootstrap_is_seeded(self):
        data = list(range(30))
        mean = lambda s: sum(s) / len(s)  # noqa: E731
        assert bootstrap_ci(data, mean, seed=1) == bootstrap_ci(data, mean, seed=1)
        lo, hi = bootstrap_ci(data, mean, seed=1)
        assert lo < 14.5 < hi
        assert all(math.isnan(x) for x in bootstrap_ci([], mean))


class TestCalibrationMaps:
    def _overconfident(self, n, seed):
        rng = random.Random(seed)
        out = []
        for _ in range(n):
            conf = rng.uniform(0.6, 1.0)
            out.append((conf, rng.random() < conf - 0.4))  # true accuracy 40 points lower
        return out

    def test_platt_fitted_on_dev_reduces_test_error(self):
        dev, test = self._overconfident(300, 1), self._overconfident(300, 2)
        platt = fit_platt(dev)
        before = brier_score(test)
        after = brier_score([(platt(c), y) for c, y in test])
        assert after < before
        assert calibration_error([(platt(c), y) for c, y in test]) < calibration_error(test)

    def test_histogram_binning(self):
        dev, test = self._overconfident(300, 3), self._overconfident(300, 4)
        hist = fit_histogram_binning(dev)
        assert brier_score([(hist(c), y) for c, y in test]) < brier_score(test)
        assert 0.0 < hist(0.95) < 1.0


class TestGates:
    def test_decided_only_by_the_interval(self):
        assert gate_decision(0.05, (0.01, 0.09), 0.10, "max") == "pass"
        assert gate_decision(0.30, (0.20, 0.40), 0.10, "max") == "fail"
        assert gate_decision(0.08, (0.02, 0.25), 0.10, "max") == "inconclusive"
        assert gate_decision(0.9, (0.7, 0.97), 0.6, "min") == "pass"
        assert gate_decision(0.4, (0.2, 0.55), 0.6, "min") == "fail"
        assert gate_decision(math.nan, (0.0, 1.0), 0.5, "min") == "inconclusive"
