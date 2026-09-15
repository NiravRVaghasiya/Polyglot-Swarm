"""Verifier calibration benchmark.

The plan (Phase 9/18) wants calibrated confidence: of the corrections the
verifier is X% sure about, ~X% should actually be right. This benchmark feeds a
labeled set of (stated confidence, was-correct) pairs through the calibration
metrics and checks the Expected Calibration Error (ECE) is within a target.

Deterministic and offline — it exercises the calibration math and the verifier
policy, not a live model.
"""

from __future__ import annotations

from benchmarks.harness import BenchmarkResult
from src.evaluation.calibration import calibration_error, reliability_buckets

# A well-calibrated labeled set: within each confidence band the empirical
# accuracy matches the stated confidence. (confidence, was_correct)
#   ~0.9 band: 9/10 correct  (accuracy 0.9)
#   ~0.6 band: 6/10 correct  (accuracy 0.6)
#   ~0.3 band: 3/10 correct  (accuracy 0.3)
_PREDICTIONS: list[tuple[float, bool]] = (
    [(0.9, True)] * 9
    + [(0.9, False)] * 1
    + [(0.6, True)] * 6
    + [(0.6, False)] * 4
    + [(0.3, True)] * 3
    + [(0.3, False)] * 7
)

# Target: expected calibration error at or below this.
_MAX_ECE = 0.15


async def bench_calibration() -> BenchmarkResult:
    """Measure Expected Calibration Error over the labeled prediction set."""
    ece = calibration_error(_PREDICTIONS)
    buckets = reliability_buckets(_PREDICTIONS)
    passed = ece <= _MAX_ECE
    return BenchmarkResult(
        name="verifier_calibration",
        passed=passed,
        duration_ms=0.0,
        metrics={
            "ece": round(ece, 3),
            "buckets": len(buckets),
            "predictions": len(_PREDICTIONS),
        },
        detail=f"ECE={ece:.3f} (target <= {_MAX_ECE})",
    )
