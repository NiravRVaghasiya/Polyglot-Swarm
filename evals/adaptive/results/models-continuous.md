# Learner-model comparison — `continuous` generator

> **Simulated learners.** Every number below comes from the simulator in `evals/adaptive/simulator.py` and reflects its assumptions. None of it is a real learner outcome.

- Train learners: 40; test learners: 60.
- 12 sessions x 10 attempts each; target = the learner's true outcome.
- Held-out predictions: 7200 (online: each attempt is predicted before it is observed).
- 95% intervals: learner-level bootstrap.

## Regime: cold

| model | AUC | log loss | Brier | ECE |
|---|---|---|---|---|
| bkt | 0.784 [0.766, 0.799] | 0.549 [0.526, 0.571] | 0.184 [0.176, 0.193] | 0.052 [0.041, 0.063] |
| elo | 0.802 [0.784, 0.819] | 0.518 [0.499, 0.537] | 0.172 [0.164, 0.179] | 0.027 [0.022, 0.040] |
| legacy_incremental | 0.694 [0.659, 0.721] | 0.660 [0.626, 0.691] | 0.214 [0.201, 0.225] | 0.069 [0.056, 0.081] |
| lkm_subskill_v1 | 0.802 [0.783, 0.819] | 0.524 [0.505, 0.543] | 0.173 [0.166, 0.181] | 0.046 [0.039, 0.058] |
| lkm_v2_rasch | 0.778 [0.757, 0.796] | 0.547 [0.525, 0.567] | 0.183 [0.174, 0.191] | 0.048 [0.042, 0.062] |

Paired difference vs `lkm_v2_rasch` (model minus baseline):

| model | AUC diff [95% CI] | log-loss diff [95% CI] |
|---|---|---|
| bkt | 0.006 [-0.007, 0.019] | 0.002 [-0.010, 0.014] |
| elo | 0.024 [0.015, 0.035] | -0.029 [-0.038, -0.020] |
| legacy_incremental | -0.084 [-0.107, -0.067] | 0.114 [0.097, 0.131] |
| lkm_subskill_v1 | 0.024 [0.016, 0.034] | -0.023 [-0.031, -0.016] |

`lkm_subskill_v1` minus `elo`: auc -0.000 [-0.004, 0.003], log_loss 0.005 [0.002, 0.009], ece 0.019 [0.012, 0.024]

`lkm_subskill_v1` 95% prediction intervals contain the true success probability 0.902 of the time (mean width 0.593).

By prior evidence on the subskill (AUC / log loss):

| model | 0 prior | 1-3 prior | 4+ prior |
|---|---|---|---|
| bkt | 0.500 / 0.713 (n=486) | 0.671 / 0.659 (n=1458) | 0.815 / 0.504 (n=5256) |
| elo | 0.717 / 0.649 (n=486) | 0.720 / 0.616 (n=1458) | 0.829 / 0.479 (n=5256) |
| legacy_incremental | 0.612 / 1.258 (n=486) | 0.625 / 0.736 (n=1458) | 0.718 / 0.584 (n=5256) |
| lkm_subskill_v1 | 0.716 / 0.634 (n=486) | 0.722 / 0.615 (n=1458) | 0.830 / 0.488 (n=5256) |
| lkm_v2_rasch | 0.716 / 0.634 (n=486) | 0.720 / 0.614 (n=1458) | 0.799 / 0.520 (n=5256) |

## Regime: warm

| model | AUC | log loss | Brier | ECE |
|---|---|---|---|---|
| bkt | 0.803 [0.785, 0.820] | 0.530 [0.513, 0.546] | 0.175 [0.168, 0.182] | 0.050 [0.038, 0.069] |
| elo | 0.803 [0.785, 0.820] | 0.516 [0.497, 0.535] | 0.171 [0.163, 0.179] | 0.025 [0.017, 0.037] |
| legacy_incremental | 0.694 [0.659, 0.721] | 0.660 [0.626, 0.691] | 0.214 [0.201, 0.225] | 0.069 [0.056, 0.081] |
| lkm_subskill_v1 | 0.802 [0.783, 0.819] | 0.524 [0.505, 0.543] | 0.173 [0.166, 0.181] | 0.046 [0.039, 0.058] |
| lkm_v2_rasch | 0.778 [0.757, 0.796] | 0.547 [0.525, 0.567] | 0.183 [0.174, 0.191] | 0.048 [0.042, 0.062] |

Paired difference vs `lkm_v2_rasch` (model minus baseline):

| model | AUC diff [95% CI] | log-loss diff [95% CI] |
|---|---|---|
| bkt | 0.025 [0.012, 0.037] | -0.017 [-0.029, -0.006] |
| elo | 0.025 [0.015, 0.036] | -0.031 [-0.041, -0.021] |
| legacy_incremental | -0.084 [-0.107, -0.067] | 0.114 [0.097, 0.131] |
| lkm_subskill_v1 | 0.024 [0.016, 0.034] | -0.023 [-0.031, -0.016] |

`lkm_subskill_v1` minus `elo`: auc -0.001 [-0.006, 0.004], log_loss 0.007 [0.003, 0.012], ece 0.021 [0.015, 0.029]

`lkm_subskill_v1` 95% prediction intervals contain the true success probability 0.902 of the time (mean width 0.593).
Tuned on training learners: half-life 21.0 days, offset prior SD 1.0.

By prior evidence on the subskill (AUC / log loss):

| model | 0 prior | 1-3 prior | 4+ prior |
|---|---|---|---|
| bkt | 0.667 / 0.647 (n=486) | 0.721 / 0.618 (n=1458) | 0.823 / 0.494 (n=5256) |
| elo | 0.710 / 0.661 (n=486) | 0.728 / 0.613 (n=1458) | 0.831 / 0.476 (n=5256) |
| legacy_incremental | 0.612 / 1.258 (n=486) | 0.625 / 0.736 (n=1458) | 0.718 / 0.584 (n=5256) |
| lkm_subskill_v1 | 0.716 / 0.634 (n=486) | 0.722 / 0.615 (n=1458) | 0.830 / 0.488 (n=5256) |
| lkm_v2_rasch | 0.716 / 0.634 (n=486) | 0.720 / 0.614 (n=1458) | 0.799 / 0.520 (n=5256) |
