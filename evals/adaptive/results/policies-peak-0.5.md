# Adaptive learning outcomes — policy simulation

> **Simulated learners.** Every number below comes from the simulator in `evals/adaptive/simulator.py` and reflects its assumptions. None of it is a real learner outcome.

- Generator: `continuous`, gain peak 0.5.
- 40 simulated learners, 20 sessions of 20.0 minutes; delayed tests at +30.0 days after the last session with no practice in between.
- Every policy faces the same learners with common random numbers; differences are paired per learner (bootstrap 95% CI).

| metric | static | existing_planner | adaptive | adaptive_predictive | adaptive_full |
|---|---|---|---|---|---|
| immediate_success | 0.678 [0.642, 0.714] | 0.667 [0.621, 0.714] | 0.770 [0.739, 0.794] | 0.744 [0.719, 0.767] | 0.714 [0.688, 0.739] |
| difficulty_adjusted_success | 0.205 [0.164, 0.245] | 0.202 [0.148, 0.257] | 0.254 [0.208, 0.288] | 0.189 [0.144, 0.228] | 0.198 [0.160, 0.237] |
| grammar_mastery_gain | 0.131 [0.113, 0.149] | 0.098 [0.082, 0.113] | 0.132 [0.111, 0.154] | 0.155 [0.136, 0.174] | 0.156 [0.137, 0.175] |
| grammar_recall_end | 0.658 [0.619, 0.698] | 0.625 [0.582, 0.670] | 0.658 [0.615, 0.700] | 0.682 [0.641, 0.723] | 0.682 [0.639, 0.726] |
| grammar_recall_delayed | 0.635 [0.597, 0.674] | 0.578 [0.534, 0.626] | 0.613 [0.572, 0.656] | 0.613 [0.571, 0.657] | 0.614 [0.572, 0.660] |
| knowledge_retention_ratio | 0.966 [0.960, 0.972] | 0.920 [0.906, 0.932] | 0.929 [0.917, 0.942] | 0.893 [0.878, 0.908] | 0.896 [0.883, 0.910] |
| objectives_completed_end | 0.358 [0.283, 0.433] | 0.411 [0.344, 0.486] | 0.528 [0.464, 0.589] | 0.486 [0.414, 0.556] | 0.492 [0.422, 0.564] |
| objectives_completed_delayed | 0.289 [0.214, 0.367] | 0.286 [0.222, 0.353] | 0.386 [0.319, 0.453] | 0.300 [0.225, 0.381] | 0.297 [0.222, 0.378] |
| words_introduced | 40.000 [40.000, 40.000] | 39.850 [39.700, 40.000] | 34.650 [33.625, 35.700] | 35.175 [33.875, 36.450] | 22.925 [21.550, 24.425] |
| words_recall_delayed | 0.435 [0.395, 0.480] | 0.421 [0.381, 0.466] | 0.460 [0.423, 0.500] | 0.456 [0.420, 0.497] | 0.577 [0.542, 0.615] |
| words_held_delayed | 3.725 [2.400, 5.325] | 3.700 [2.375, 5.300] | 3.850 [2.500, 5.450] | 3.850 [2.500, 5.450] | 4.275 [2.850, 5.925] |
| grammar_gain_per_hour | 0.200 [0.173, 0.228] | 0.143 [0.119, 0.165] | 0.183 [0.154, 0.214] | 0.217 [0.192, 0.243] | 0.219 [0.194, 0.246] |
| words_held_per_hour | 0.633 [0.408, 0.905] | 0.603 [0.386, 0.860] | 0.596 [0.390, 0.840] | 0.604 [0.392, 0.856] | 0.676 [0.454, 0.938] |
| recommendation_relevance | 0.936 [0.922, 0.951] | 0.907 [0.863, 0.947] | 0.982 [0.969, 0.990] | 0.982 [0.975, 0.989] | 0.984 [0.978, 0.990] |
| practice_minutes | 353.000 [353.000, 353.000] | 369.875 [368.650, 371.075] | 388.625 [386.050, 390.675] | 384.900 [382.875, 386.775] | 383.000 [380.625, 385.250] |

Paired differences against `existing_planner` (policy minus baseline):

| policy | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_held_delayed | grammar_gain_per_hour | recommendation_relevance |
|---|---|---|---|---|---|---|
| static | 0.011 [-0.024, 0.049] | 0.057 [0.046, 0.068] | 0.003 [-0.025, 0.031] | 0.025 [0.000, 0.075] | 0.057 [0.040, 0.075] | 0.029 [-0.010, 0.073] |
| adaptive | 0.102 [0.062, 0.148] | 0.035 [0.025, 0.045] | 0.100 [0.061, 0.136] | 0.150 [0.025, 0.300] | 0.040 [0.018, 0.062] | 0.075 [0.034, 0.122] |
| adaptive_predictive | 0.077 [0.037, 0.117] | 0.035 [0.026, 0.045] | 0.014 [-0.022, 0.050] | 0.150 [0.025, 0.300] | 0.074 [0.055, 0.094] | 0.075 [0.037, 0.120] |
| adaptive_full | 0.047 [0.006, 0.088] | 0.036 [0.028, 0.045] | 0.011 [-0.028, 0.044] | 0.575 [0.325, 0.850] | 0.076 [0.058, 0.097] | 0.077 [0.038, 0.122] |

Paired differences isolating one capability (policy minus its baseline):

| comparison | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_introduced | words_recall_delayed | words_held_delayed | words_held_per_hour | grammar_gain_per_hour |
|---|---|---|---|---|---|---|---|---|
| adaptive_vs_static | 0.091 [0.069, 0.114] | -0.022 [-0.029, -0.015] | 0.097 [0.061, 0.131] | -5.350 [-6.375, -4.400] | 0.024 [0.018, 0.030] | 0.125 [0.025, 0.225] | -0.038 [-0.063, -0.015] | -0.017 [-0.035, 0.001] |
| prediction_and_difficulty | -0.025 [-0.040, -0.011] | -0.000 [-0.009, 0.009] | -0.086 [-0.117, -0.058] | 0.525 [-0.275, 1.300] | -0.004 [-0.010, 0.002] | 0.000 [0.000, 0.000] | 0.009 [0.002, 0.016] | 0.034 [0.011, 0.057] |
| fsrs_integration_vs_fsrs_only | -0.030 [-0.044, -0.019] | 0.001 [-0.004, 0.006] | -0.003 [-0.028, 0.019] | -12.250 [-13.225, -11.150] | 0.121 [0.109, 0.133] | 0.425 [0.250, 0.600] | 0.072 [0.043, 0.101] | 0.002 [-0.008, 0.013] |
| full_vs_static | 0.036 [0.017, 0.055] | -0.021 [-0.030, -0.012] | 0.008 [-0.019, 0.033] | -17.075 [-18.375, -15.625] | 0.142 [0.128, 0.154] | 0.550 [0.300, 0.800] | 0.043 [0.003, 0.081] | 0.019 [0.003, 0.034] |

## Prediction accuracy inside the adaptive policy

- Next-attempt success predictions (made before each attempt): n=5676, AUC 0.662, log loss 0.528, Brier 0.173, ECE 0.078.
- Delayed-recall predictions for vocabulary (FSRS retrievability at the delayed test vs the true recall probability): n=902, mean predicted 0.718, mean true 0.597, rank correlation 0.589.

Metric definitions are in `docs/adaptive-learning.md`. Immediate performance and delayed retention are measured separately: immediate = outcomes during sessions; delayed = true recall probability after the delay.
