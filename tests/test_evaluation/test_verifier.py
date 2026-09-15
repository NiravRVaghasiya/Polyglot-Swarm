"""Phase 9 tests: verifier (accept/revise/reject/abstain), policies, conflict
reconciliation, and calibration."""

from __future__ import annotations

from src.evaluation import calibration, conflict, verifier
from src.evaluation.policies import ABSTAIN_THRESHOLD, Decision, decide, is_high_impact


def _err(original="x", *, classification="wrong", severity="moderate", confidence=1.0):
    return {
        "original": original,
        "correction": f"fixed {original}",
        "rule": "r",
        "classification": classification,
        "severity": severity,
        "confidence": confidence,
    }


class TestPolicies:
    def test_high_impact_true_for_genuine_moderate(self):
        assert is_high_impact(_err(classification="wrong", severity="moderate"))
        assert is_high_impact(_err(classification="wrong", severity="critical"))

    def test_low_impact_for_acceptable_or_minor(self):
        assert not is_high_impact(_err(classification="regional"))
        assert not is_high_impact(_err(classification="wrong", severity="minor"))

    def test_decide_thresholds(self):
        assert decide(0.9) == Decision.ACCEPT
        assert decide(0.9, has_revision=True) == Decision.REVISE
        assert decide(ABSTAIN_THRESHOLD - 0.01) == Decision.ABSTAIN


class TestVerifier:
    def test_accepts_confident_errors(self):
        errs = [_err("a", confidence=0.9), _err("b", confidence=0.95)]
        out = verifier.verify_errors(errs)
        assert len(out.kept) == 2
        assert out.dropped_indices == []

    def test_abstains_on_low_confidence(self):
        errs = [_err("a", confidence=0.2)]
        out = verifier.verify_errors(errs)
        assert out.kept == []
        assert out.abstained == 1
        assert 0 in out.dropped_indices

    def test_llm_reject_drops(self):
        errs = [_err("a", confidence=0.9)]
        out = verifier.verify_errors(
            errs, llm_decisions={0: {"decision": "reject", "confidence": 0.9}}
        )
        assert out.kept == []
        assert out.decisions[0] == "reject"

    def test_llm_revise_applies_revision(self):
        errs = [_err("a", confidence=0.9)]
        out = verifier.verify_errors(
            errs,
            llm_decisions={0: {"decision": "revise", "confidence": 0.9, "revised": "better fix"}},
        )
        assert len(out.kept) == 1
        assert out.kept[0]["correction"] == "better fix"
        assert out.revised == 1

    def test_llm_abstain_suppresses(self):
        errs = [_err("a", confidence=0.9)]
        out = verifier.verify_errors(
            errs, llm_decisions={0: {"decision": "abstain", "confidence": 0.4}}
        )
        assert out.kept == []
        assert out.abstained == 1

    def test_legacy_override_indices_drop(self):
        errs = [_err("a", confidence=0.9), _err("b", confidence=0.9)]
        out = verifier.verify_errors(errs, override_indices={1})
        assert [e["original"] for e in out.kept] == ["a"]
        assert 1 in out.dropped_indices

    def test_culture_conflict_drops_register_error(self):
        errs = [_err("pa'l", classification="informal", confidence=0.9)]
        out = verifier.verify_errors(errs, cultural_notes=["informal is fine with friends"])
        assert out.kept == []  # register form endorsed by culture -> not corrected


class TestConflict:
    def test_reconcile_flags_informal_conflict(self):
        errs = [{"original": "pa'l", "classification": "informal"}]
        conflicts = conflict.reconcile_grammar_culture(errs, ["informal is fine here"])
        assert conflicts and conflicts[0]["index"] == 0

    def test_no_conflict_for_wrong_error(self):
        errs = [{"original": "soy hambre", "classification": "wrong"}]
        assert conflict.reconcile_grammar_culture(errs, ["informal is fine"]) == []


class TestCalibration:
    def test_perfect_calibration_zero_ece(self):
        preds = [(0.9, True)] * 9 + [(0.9, False)] * 1
        assert calibration.calibration_error(preds) < 0.05

    def test_overconfident_has_error(self):
        preds = [(0.95, False)] * 10  # very confident, always wrong
        assert calibration.calibration_error(preds) > 0.5

    def test_empty_is_zero(self):
        assert calibration.calibration_error([]) == 0.0

    def test_reliability_buckets_omit_empty(self):
        buckets = calibration.reliability_buckets([(0.9, True), (0.9, False)])
        assert len(buckets) == 1
        assert buckets[0].count == 2

    def test_bucket_gap(self):
        buckets = calibration.reliability_buckets([(0.9, False)] * 10)
        assert buckets[0].gap > 0.5


class TestCalibrationBenchmark:
    async def test_benchmark_passes(self):
        from benchmarks.calibration_bench import bench_calibration

        result = await bench_calibration()
        assert result.passed
        assert result.metrics["ece"] <= 0.15
