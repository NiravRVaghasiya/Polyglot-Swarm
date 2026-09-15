"""Hand-labeled assessment dataset: belief -> expert-equivalent CEFR band.

Each case pairs a (mastery, uncertainty, sample_size) belief — the shape
:class:`src.learner.mastery_engine.SkillBelief` produces — with the CEFR band an
expert rater would assign given that evidence. Spans all six bands plus a few
boundary/low-evidence cases, since those are where a mis-calibrated confidence
function would first show up.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump when cases are added/changed/removed.
DATASET_VERSION = "2026.09.0"

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


@dataclass(frozen=True)
class AssessmentCase:
    """One (belief, expert CEFR label) pair."""

    name: str
    mastery: float
    uncertainty: float
    sample_size: float
    expert_cefr: str


CASES: list[AssessmentCase] = [
    # Well-evidenced, unambiguous cases at each band's midpoint.
    AssessmentCase(
        "beginner_well_evidenced", mastery=0.08, uncertainty=0.2, sample_size=20, expert_cefr="A1"
    ),
    AssessmentCase(
        "elementary_well_evidenced", mastery=0.25, uncertainty=0.2, sample_size=20, expert_cefr="A2"
    ),
    AssessmentCase(
        "intermediate_well_evidenced",
        mastery=0.45,
        uncertainty=0.2,
        sample_size=20,
        expert_cefr="B1",
    ),
    AssessmentCase(
        "upper_intermediate_well_evidenced",
        mastery=0.65,
        uncertainty=0.2,
        sample_size=20,
        expert_cefr="B2",
    ),
    AssessmentCase(
        "advanced_well_evidenced", mastery=0.82, uncertainty=0.2, sample_size=20, expert_cefr="C1"
    ),
    AssessmentCase(
        "proficient_well_evidenced", mastery=0.96, uncertainty=0.1, sample_size=30, expert_cefr="C2"
    ),
    # Boundary cases, just inside each band edge.
    AssessmentCase(
        "boundary_a1_a2", mastery=0.14, uncertainty=0.3, sample_size=10, expert_cefr="A1"
    ),
    AssessmentCase(
        "boundary_a2_b1", mastery=0.36, uncertainty=0.3, sample_size=10, expert_cefr="B1"
    ),
    AssessmentCase(
        "boundary_b1_b2", mastery=0.56, uncertainty=0.3, sample_size=10, expert_cefr="B2"
    ),
    AssessmentCase(
        "boundary_b2_c1", mastery=0.76, uncertainty=0.3, sample_size=10, expert_cefr="C1"
    ),
    AssessmentCase(
        "boundary_c1_c2", mastery=0.91, uncertainty=0.2, sample_size=15, expert_cefr="C2"
    ),
    # Low-evidence cases: a real assessor would be uncertain too, but the
    # mastery-to-band mapping should still track the point estimate.
    AssessmentCase(
        "low_evidence_beginner", mastery=0.1, uncertainty=0.9, sample_size=1, expert_cefr="A1"
    ),
    AssessmentCase(
        "low_evidence_intermediate", mastery=0.5, uncertainty=0.85, sample_size=2, expert_cefr="B1"
    ),
]


@dataclass(frozen=True)
class CalibrationCase:
    """A (uncertainty, sample_size) pair plus whether the point-estimate band
    ended up matching the eventual expert-labeled band.

    Unlike ``CASES`` above (where the expert label is *defined* to match the
    predicted band, to test the mapping's ordering), calibration needs a
    realistic mix of hits and misses at each confidence level: a real
    low-evidence estimate is *often* revised once more evidence comes in, while
    a well-evidenced one rarely is. ``confidence_from(uncertainty, sample_size)``
    should track that — this dataset is what lets calibration_error() check it.
    """

    name: str
    uncertainty: float
    sample_size: float
    matched_expert_band: bool


# (uncertainty, sample_size) chosen so confidence_from lands in three clearly
# separated bands, each with a hit rate close to its own confidence — i.e. a
# well-calibrated ground truth, analogous to benchmarks/calibration_bench.py's
# hand-built (confidence, correct) set.
CALIBRATION_CASES: list[CalibrationCase] = (
    # High confidence (~0.83-0.88): mostly matches (9/10).
    [
        CalibrationCase(
            f"high_conf_hit_{i}", uncertainty=0.05, sample_size=12 + i, matched_expert_band=True
        )
        for i in range(9)
    ]
    + [
        CalibrationCase(
            "high_conf_miss", uncertainty=0.05, sample_size=12, matched_expert_band=False
        )
    ]
    # Mid confidence (~0.62-0.68): a genuine mix (6/10).
    + [
        CalibrationCase(
            f"mid_conf_hit_{i}", uncertainty=0.08, sample_size=3, matched_expert_band=True
        )
        for i in range(6)
    ]
    + [
        CalibrationCase(
            f"mid_conf_miss_{i}", uncertainty=0.08, sample_size=3, matched_expert_band=False
        )
        for i in range(4)
    ]
    # Low confidence (~0.12-0.20): mostly misses (2/10) — sparse evidence means
    # the point estimate rarely survives once more evidence arrives.
    + [
        CalibrationCase(
            f"low_conf_hit_{i}", uncertainty=0.9, sample_size=1, matched_expert_band=True
        )
        for i in range(2)
    ]
    + [
        CalibrationCase(
            f"low_conf_miss_{i}", uncertainty=0.9, sample_size=1, matched_expert_band=False
        )
        for i in range(8)
    ]
)
