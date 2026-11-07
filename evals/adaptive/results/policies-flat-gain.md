# Adaptive learning outcomes — policy simulation

> **Simulated learners.** Every number below comes from the simulator in `evals/adaptive/simulator.py` and reflects its assumptions. None of it is a real learner outcome.

- Generator: `continuous`, gain peak flat (difficulty does not matter).
- 40 simulated learners, 20 sessions of 20.0 minutes; delayed tests at +30.0 days after the last session with no practice in between.
- Every policy faces the same learners with common random numbers; differences are paired per learner (bootstrap 95% CI).

| metric | static | existing_planner | adaptive | adaptive_predictive | adaptive_full |
|---|---|---|---|---|---|
| immediate_success | 0.695 [0.659, 0.730] | 0.683 [0.641, 0.727] | 0.787 [0.759, 0.811] | 0.755 [0.730, 0.777] | 0.721 [0.694, 0.748] |
| difficulty_adjusted_success | 0.234 [0.193, 0.273] | 0.230 [0.178, 0.282] | 0.278 [0.235, 0.313] | 0.222 [0.178, 0.263] | 0.219 [0.179, 0.260] |
| grammar_mastery_gain | 0.172 [0.151, 0.194] | 0.112 [0.095, 0.129] | 0.160 [0.135, 0.188] | 0.199 [0.176, 0.222] | 0.196 [0.176, 0.216] |
| grammar_recall_end | 0.699 [0.660, 0.739] | 0.639 [0.595, 0.685] | 0.687 [0.645, 0.728] | 0.726 [0.685, 0.769] | 0.722 [0.677, 0.769] |
| grammar_recall_delayed | 0.676 [0.637, 0.716] | 0.593 [0.546, 0.642] | 0.645 [0.602, 0.688] | 0.662 [0.618, 0.710] | 0.662 [0.616, 0.710] |
| knowledge_retention_ratio | 0.968 [0.962, 0.973] | 0.921 [0.908, 0.934] | 0.937 [0.921, 0.951] | 0.907 [0.892, 0.922] | 0.913 [0.899, 0.927] |
| objectives_completed_end | 0.483 [0.406, 0.564] | 0.422 [0.356, 0.500] | 0.578 [0.514, 0.644] | 0.625 [0.547, 0.703] | 0.617 [0.531, 0.694] |
| objectives_completed_delayed | 0.431 [0.350, 0.517] | 0.336 [0.272, 0.406] | 0.481 [0.414, 0.550] | 0.431 [0.350, 0.506] | 0.458 [0.375, 0.542] |
| words_introduced | 40.000 [40.000, 40.000] | 39.800 [39.400, 40.000] | 34.300 [33.100, 35.475] | 35.425 [34.275, 36.650] | 24.050 [22.350, 25.875] |
| words_recall_delayed | 0.452 [0.411, 0.498] | 0.431 [0.391, 0.476] | 0.482 [0.444, 0.523] | 0.473 [0.437, 0.516] | 0.578 [0.542, 0.616] |
| words_held_delayed | 4.775 [3.275, 6.525] | 4.475 [3.000, 6.225] | 5.275 [3.625, 7.150] | 5.350 [3.675, 7.275] | 5.575 [3.950, 7.375] |
| grammar_gain_per_hour | 0.263 [0.231, 0.297] | 0.164 [0.139, 0.188] | 0.222 [0.188, 0.262] | 0.281 [0.248, 0.312] | 0.276 [0.249, 0.304] |
| words_held_per_hour | 0.812 [0.557, 1.109] | 0.728 [0.489, 1.011] | 0.816 [0.556, 1.110] | 0.845 [0.579, 1.152] | 0.887 [0.630, 1.176] |
| recommendation_relevance | 0.947 [0.936, 0.958] | 0.927 [0.891, 0.958] | 0.982 [0.972, 0.989] | 0.985 [0.978, 0.990] | 0.984 [0.978, 0.989] |
| practice_minutes | 353.000 [353.000, 353.000] | 370.100 [368.900, 371.250] | 388.525 [386.200, 390.550] | 383.000 [380.825, 385.100] | 381.850 [379.550, 384.075] |

Paired differences against `existing_planner` (policy minus baseline):

| policy | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_held_delayed | grammar_gain_per_hour | recommendation_relevance |
|---|---|---|---|---|---|---|
| static | 0.011 [-0.024, 0.046] | 0.083 [0.068, 0.099] | 0.094 [0.050, 0.139] | 0.300 [0.025, 0.575] | 0.099 [0.076, 0.123] | 0.020 [-0.010, 0.056] |
| adaptive | 0.104 [0.065, 0.147] | 0.052 [0.036, 0.067] | 0.144 [0.106, 0.183] | 0.800 [0.450, 1.200] | 0.058 [0.024, 0.089] | 0.055 [0.020, 0.095] |
| adaptive_predictive | 0.072 [0.037, 0.108] | 0.070 [0.053, 0.086] | 0.094 [0.042, 0.142] | 0.875 [0.500, 1.275] | 0.117 [0.086, 0.148] | 0.058 [0.024, 0.095] |
| adaptive_full | 0.037 [-0.000, 0.076] | 0.069 [0.055, 0.085] | 0.122 [0.072, 0.169] | 1.100 [0.700, 1.525] | 0.112 [0.085, 0.143] | 0.057 [0.025, 0.094] |

Paired differences isolating one capability (policy minus its baseline):

| comparison | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_introduced | words_recall_delayed | words_held_delayed | words_held_per_hour | grammar_gain_per_hour |
|---|---|---|---|---|---|---|---|---|
| adaptive_vs_static | 0.092 [0.072, 0.114] | -0.031 [-0.042, -0.021] | 0.050 [0.014, 0.086] | -5.700 [-6.875, -4.525] | 0.030 [0.021, 0.038] | 0.500 [0.250, 0.775] | 0.005 [-0.036, 0.048] | -0.041 [-0.063, -0.022] |
| prediction_and_difficulty | -0.032 [-0.046, -0.019] | 0.017 [0.006, 0.031] | -0.050 [-0.092, -0.008] | 1.125 [0.200, 1.975] | -0.008 [-0.015, -0.002] | 0.075 [-0.025, 0.175] | 0.029 [0.011, 0.047] | 0.058 [0.030, 0.090] |
| fsrs_integration_vs_fsrs_only | -0.035 [-0.047, -0.023] | -0.000 [-0.008, 0.007] | 0.028 [-0.011, 0.064] | -11.375 [-12.675, -10.025] | 0.104 [0.090, 0.118] | 0.225 [-0.050, 0.550] | 0.041 [-0.004, 0.092] | -0.004 [-0.021, 0.010] |
| full_vs_static | 0.026 [0.006, 0.045] | -0.014 [-0.028, 0.000] | 0.028 [-0.014, 0.067] | -15.950 [-17.675, -14.250] | 0.125 [0.107, 0.144] | 0.800 [0.475, 1.175] | 0.075 [0.024, 0.134] | 0.013 [-0.012, 0.037] |

## Prediction accuracy inside the adaptive policy

- Next-attempt success predictions (made before each attempt): n=5502, AUC 0.702, log loss 0.507, Brier 0.164, ECE 0.088.
- Delayed-recall predictions for vocabulary (FSRS retrievability at the delayed test vs the true recall probability): n=935, mean predicted 0.712, mean true 0.604, rank correlation 0.548.

Metric definitions are in `docs/adaptive-learning.md`. Immediate performance and delayed retention are measured separately: immediate = outcomes during sessions; delayed = true recall probability after the delay.
