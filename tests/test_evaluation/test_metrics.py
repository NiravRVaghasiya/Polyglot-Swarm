"""Phase 18 tests: shared evaluation metrics (precision/recall/F1/MAE/correlation)."""

from __future__ import annotations

from src.evaluation.metrics import (
    PrecisionRecallResult,
    f1_score,
    false_positive_rate,
    mean_absolute_error,
    pearson_correlation,
    precision,
    recall,
)


class TestPrecisionRecall:
    def test_basic_precision_recall(self):
        assert precision(tp=3, fp=1) == 0.75
        assert recall(tp=3, fn=1) == 0.75

    def test_precision_defaults_to_one_with_no_predictions(self):
        assert precision(tp=0, fp=0) == 1.0

    def test_recall_defaults_to_one_with_no_positive_cases(self):
        assert recall(tp=0, fn=0) == 1.0

    def test_f1_harmonic_mean(self):
        assert f1_score(1.0, 1.0) == 1.0
        assert round(f1_score(0.5, 0.5), 3) == 0.5

    def test_f1_zero_when_both_zero(self):
        assert f1_score(0.0, 0.0) == 0.0

    def test_false_positive_rate(self):
        assert false_positive_rate(fp=2, negatives=4) == 0.5
        assert false_positive_rate(fp=0, negatives=0) == 0.0


class TestPrecisionRecallResult:
    def test_from_counts(self):
        result = PrecisionRecallResult.from_counts(tp=8, fp=2, fn=1)
        assert result.precision == 0.8
        assert round(result.recall, 3) == round(8 / 9, 3)
        assert result.f1 > 0.0

    def test_as_dict_rounds(self):
        result = PrecisionRecallResult.from_counts(tp=1, fp=0, fn=0)
        d = result.as_dict()
        assert d == {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}


class TestMeanAbsoluteError:
    def test_empty_is_zero(self):
        assert mean_absolute_error([]) == 0.0

    def test_perfect_predictions(self):
        assert mean_absolute_error([(1.0, 1.0), (2.0, 2.0)]) == 0.0

    def test_known_error(self):
        assert mean_absolute_error([(1.0, 0.0), (0.0, 1.0)]) == 1.0


class TestPearsonCorrelation:
    def test_perfect_positive_correlation(self):
        assert round(pearson_correlation([(1, 1), (2, 2), (3, 3)]), 3) == 1.0

    def test_perfect_negative_correlation(self):
        assert round(pearson_correlation([(1, 3), (2, 2), (3, 1)]), 3) == -1.0

    def test_no_variance_returns_zero(self):
        assert pearson_correlation([(1, 1), (1, 2), (1, 3)]) == 0.0

    def test_too_few_points_returns_zero(self):
        assert pearson_correlation([(1, 1)]) == 0.0
        assert pearson_correlation([]) == 0.0
