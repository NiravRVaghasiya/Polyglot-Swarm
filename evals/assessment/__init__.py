"""Assessment evaluation suite.

Scores the pure functions behind the multidimensional CEFR profile
(:mod:`src.assessment.cefr_profile`) against hand-labeled cases: given a
mastery/uncertainty/sample-size belief, does :func:`mastery_to_cefr` +
:func:`confidence_from` land where an examiner-calibrated system should?

Plan (Phase 18) metrics and their status here:

- **correlation with expert ratings** — measured: each case's mastery score is
  paired with an "expert-equivalent" CEFR band (encoded as its ordinal
  position A1..C2), and Pearson correlation is computed between mastery and
  that ordinal.
- **absolute error** — measured: mean absolute error between the predicted
  CEFR band's ordinal and the expert-labeled ordinal.
- **calibration** — measured: reuses :mod:`src.evaluation.calibration` over
  (confidence, was-correct) pairs, where "correct" means the predicted band
  matched the expert label.
- **confidence coverage** — measured: whether ``confidence_from`` actually
  produces low confidence for low-evidence/high-uncertainty cases and high
  confidence for well-evidenced ones (a monotonicity property, not a live
  human-rating comparison).

No live model or human rater is involved — "expert ratings" here means the
hand-labeled ground truth in the dataset, standing in for what a real
proficiency-exam correlation study would supply.
"""
