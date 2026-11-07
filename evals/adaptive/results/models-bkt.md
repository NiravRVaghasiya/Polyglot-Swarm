# Learner-model comparison — `bkt` generator

> **Simulated learners.** Every number below comes from the simulator in `evals/adaptive/simulator.py` and reflects its assumptions. None of it is a real learner outcome.

- Train learners: 40; test learners: 60.
- 12 sessions x 10 attempts each; target = the learner's true outcome.
- Held-out predictions: 7200 (online: each attempt is predicted before it is observed).
- 95% intervals: learner-level bootstrap.

## Regime: cold

| model | AUC | log loss | Brier | ECE |
|---|---|---|---|---|
| bkt | 0.868 [0.853, 0.879] | 0.432 [0.417, 0.449] | 0.134 [0.128, 0.139] | 0.068 [0.059, 0.077] |
| elo | 0.822 [0.807, 0.833] | 0.512 [0.497, 0.527] | 0.167 [0.162, 0.173] | 0.058 [0.052, 0.070] |
| legacy_incremental | 0.663 [0.640, 0.686] | 0.722 [0.704, 0.740] | 0.241 [0.236, 0.245] | 0.151 [0.136, 0.168] |
| lkm_subskill_v1 | 0.819 [0.804, 0.832] | 0.537 [0.524, 0.549] | 0.178 [0.172, 0.183] | 0.100 [0.090, 0.114] |
| lkm_v2_rasch | 0.701 [0.681, 0.720] | 0.629 [0.614, 0.645] | 0.219 [0.212, 0.225] | 0.100 [0.088, 0.113] |

Paired difference vs `lkm_v2_rasch` (model minus baseline):

| model | AUC diff [95% CI] | log-loss diff [95% CI] |
|---|---|---|
| bkt | 0.167 [0.148, 0.186] | -0.196 [-0.213, -0.181] |
| elo | 0.121 [0.104, 0.138] | -0.117 [-0.131, -0.103] |
| legacy_incremental | -0.038 [-0.060, -0.016] | 0.093 [0.073, 0.109] |
| lkm_subskill_v1 | 0.118 [0.104, 0.133] | -0.092 [-0.105, -0.080] |

`lkm_subskill_v1` minus `elo`: auc -0.003 [-0.008, 0.003], log_loss 0.025 [0.019, 0.031], ece 0.042 [0.031, 0.048]

`lkm_subskill_v1` 95% prediction intervals contain the true success probability 0.230 of the time (mean width 0.603).

By prior evidence on the subskill (AUC / log loss):

| model | 0 prior | 1-3 prior | 4+ prior |
|---|---|---|---|
| bkt | 0.500 / 0.622 (n=486) | 0.796 / 0.526 (n=1458) | 0.854 / 0.389 (n=5256) |
| elo | 0.643 / 0.777 (n=486) | 0.772 / 0.566 (n=1458) | 0.842 / 0.473 (n=5256) |
| legacy_incremental | 0.474 / 1.242 (n=486) | 0.561 / 0.749 (n=1458) | 0.643 / 0.666 (n=5256) |
| lkm_subskill_v1 | 0.627 / 0.690 (n=486) | 0.771 / 0.563 (n=1458) | 0.831 / 0.516 (n=5256) |
| lkm_v2_rasch | 0.627 / 0.690 (n=486) | 0.669 / 0.635 (n=1458) | 0.681 / 0.621 (n=5256) |

## Regime: warm

| model | AUC | log loss | Brier | ECE |
|---|---|---|---|---|
| bkt | 0.869 [0.855, 0.881] | 0.422 [0.404, 0.439] | 0.129 [0.123, 0.135] | 0.036 [0.024, 0.049] |
| elo | 0.810 [0.794, 0.822] | 0.520 [0.506, 0.535] | 0.171 [0.165, 0.177] | 0.049 [0.042, 0.060] |
| legacy_incremental | 0.663 [0.640, 0.686] | 0.722 [0.704, 0.740] | 0.241 [0.236, 0.245] | 0.151 [0.136, 0.168] |
| lkm_subskill_v1 | 0.835 [0.821, 0.847] | 0.516 [0.501, 0.530] | 0.169 [0.163, 0.175] | 0.102 [0.090, 0.116] |
| lkm_v2_rasch | 0.701 [0.681, 0.720] | 0.629 [0.614, 0.645] | 0.219 [0.212, 0.225] | 0.100 [0.088, 0.113] |

Paired difference vs `lkm_v2_rasch` (model minus baseline):

| model | AUC diff [95% CI] | log-loss diff [95% CI] |
|---|---|---|
| bkt | 0.168 [0.150, 0.187] | -0.207 [-0.225, -0.190] |
| elo | 0.109 [0.090, 0.127] | -0.109 [-0.125, -0.095] |
| legacy_incremental | -0.038 [-0.060, -0.016] | 0.093 [0.073, 0.109] |
| lkm_subskill_v1 | 0.134 [0.117, 0.150] | -0.112 [-0.129, -0.097] |

`lkm_subskill_v1` minus `elo`: auc 0.025 [0.019, 0.032], log_loss -0.004 [-0.011, 0.004], ece 0.053 [0.040, 0.059]

`lkm_subskill_v1` 95% prediction intervals contain the true success probability 0.432 of the time (mean width 0.655).
Tuned on training learners: half-life 21.0 days, offset prior SD 1.5.

By prior evidence on the subskill (AUC / log loss):

| model | 0 prior | 1-3 prior | 4+ prior |
|---|---|---|---|
| bkt | 0.669 / 0.539 (n=486) | 0.819 / 0.504 (n=1458) | 0.850 / 0.388 (n=5256) |
| elo | 0.643 / 0.888 (n=486) | 0.776 / 0.569 (n=1458) | 0.841 / 0.472 (n=5256) |
| legacy_incremental | 0.474 / 1.242 (n=486) | 0.561 / 0.749 (n=1458) | 0.643 / 0.666 (n=5256) |
| lkm_subskill_v1 | 0.627 / 0.690 (n=486) | 0.796 / 0.535 (n=1458) | 0.847 / 0.495 (n=5256) |
| lkm_v2_rasch | 0.627 / 0.690 (n=486) | 0.669 / 0.635 (n=1458) | 0.681 / 0.621 (n=5256) |
