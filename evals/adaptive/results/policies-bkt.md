# Adaptive learning outcomes — policy simulation

> **Simulated learners.** Every number below comes from the simulator in `evals/adaptive/simulator.py` and reflects its assumptions. None of it is a real learner outcome.

- Generator: `bkt`, gain peak 0.7.
- 40 simulated learners, 20 sessions of 20.0 minutes; delayed tests at +30.0 days after the last session with no practice in between.
- Every policy faces the same learners with common random numbers; differences are paired per learner (bootstrap 95% CI).

| metric | static | existing_planner | adaptive | adaptive_predictive | adaptive_full |
|---|---|---|---|---|---|
| immediate_success | 0.586 [0.566, 0.607] | 0.694 [0.664, 0.719] | 0.706 [0.689, 0.723] | 0.660 [0.645, 0.676] | 0.653 [0.636, 0.672] |
| difficulty_adjusted_success | 0.199 [0.172, 0.226] | 0.270 [0.229, 0.307] | 0.274 [0.251, 0.297] | 0.148 [0.117, 0.182] | 0.148 [0.115, 0.180] |
| grammar_mastery_gain | 0.355 [0.311, 0.401] | 0.276 [0.229, 0.319] | 0.286 [0.238, 0.337] | 0.274 [0.226, 0.322] | 0.211 [0.179, 0.244] |
| grammar_recall_end | 0.678 [0.649, 0.705] | 0.599 [0.565, 0.632] | 0.609 [0.560, 0.658] | 0.597 [0.556, 0.637] | 0.534 [0.494, 0.572] |
| grammar_recall_delayed | 0.507 [0.485, 0.527] | 0.450 [0.425, 0.476] | 0.456 [0.420, 0.492] | 0.447 [0.417, 0.476] | 0.400 [0.371, 0.428] |
| knowledge_retention_ratio | 0.748 [0.747, 0.748] | 0.751 [0.748, 0.755] | 0.749 [0.748, 0.750] | 0.749 [0.748, 0.750] | 0.750 [0.749, 0.751] |
| objectives_completed_end | 0.356 [0.325, 0.389] | 0.558 [0.514, 0.608] | 0.564 [0.500, 0.631] | 0.461 [0.417, 0.511] | 0.344 [0.314, 0.378] |
| objectives_completed_delayed | 0.000 [0.000, 0.000] | 0.008 [0.000, 0.022] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| words_introduced | 40.000 [40.000, 40.000] | 39.600 [39.200, 39.900] | 25.375 [24.325, 26.350] | 26.100 [24.875, 27.425] | 19.475 [18.500, 20.550] |
| words_recall_delayed | 0.292 [0.275, 0.306] | 0.218 [0.200, 0.236] | 0.385 [0.363, 0.407] | 0.384 [0.363, 0.409] | 0.500 [0.481, 0.519] |
| words_held_delayed | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| grammar_gain_per_hour | 0.543 [0.476, 0.614] | 0.400 [0.333, 0.462] | 0.400 [0.333, 0.471] | 0.387 [0.320, 0.453] | 0.298 [0.254, 0.345] |
| words_held_per_hour | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| recommendation_relevance | 0.891 [0.881, 0.901] | 0.907 [0.888, 0.925] | 0.949 [0.941, 0.957] | 0.936 [0.927, 0.945] | 0.951 [0.942, 0.959] |
| practice_minutes | 353.000 [353.000, 353.000] | 372.450 [370.650, 374.000] | 387.175 [384.650, 389.500] | 382.025 [379.300, 384.500] | 382.525 [381.350, 383.800] |

Paired differences against `existing_planner` (policy minus baseline):

| policy | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_held_delayed | grammar_gain_per_hour | recommendation_relevance |
|---|---|---|---|---|---|---|
| static | -0.108 [-0.137, -0.079] | 0.056 [0.029, 0.085] | -0.008 [-0.022, 0.000] | 0.000 [0.000, 0.000] | 0.143 [0.087, 0.200] | -0.016 [-0.036, 0.005] |
| adaptive | 0.012 [-0.019, 0.044] | 0.006 [-0.024, 0.038] | -0.008 [-0.022, 0.000] | 0.000 [0.000, 0.000] | 0.000 [-0.058, 0.061] | 0.042 [0.022, 0.064] |
| adaptive_predictive | -0.034 [-0.060, -0.009] | -0.003 [-0.038, 0.031] | -0.008 [-0.022, 0.000] | 0.000 [0.000, 0.000] | -0.013 [-0.079, 0.052] | 0.029 [0.010, 0.049] |
| adaptive_full | -0.040 [-0.075, -0.007] | -0.050 [-0.081, -0.020] | -0.008 [-0.022, 0.000] | 0.000 [0.000, 0.000] | -0.101 [-0.161, -0.045] | 0.044 [0.023, 0.065] |

Paired differences isolating one capability (policy minus its baseline):

| comparison | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_introduced | words_recall_delayed | words_held_delayed | words_held_per_hour | grammar_gain_per_hour |
|---|---|---|---|---|---|---|---|---|
| adaptive_vs_static | 0.120 [0.099, 0.140] | -0.051 [-0.089, -0.015] | 0.000 [0.000, 0.000] | -14.625 [-15.775, -13.525] | 0.094 [0.073, 0.115] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | -0.143 [-0.220, -0.072] |
| prediction_and_difficulty | -0.046 [-0.064, -0.029] | -0.009 [-0.037, 0.020] | 0.000 [0.000, 0.000] | 0.725 [-0.175, 1.700] | -0.001 [-0.015, 0.012] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | -0.013 [-0.068, 0.042] |
| fsrs_integration_vs_fsrs_only | -0.007 [-0.026, 0.010] | -0.047 [-0.078, -0.017] | 0.000 [0.000, 0.000] | -6.625 [-7.500, -5.700] | 0.116 [0.094, 0.139] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | -0.088 [-0.148, -0.030] |
| full_vs_static | 0.067 [0.042, 0.093] | -0.106 [-0.135, -0.078] | 0.000 [0.000, 0.000] | -20.525 [-21.575, -19.500] | 0.209 [0.187, 0.232] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | -0.245 [-0.303, -0.185] |

## Prediction accuracy inside the adaptive policy

- Next-attempt success predictions (made before each attempt): n=5103, AUC 0.783, log loss 0.478, Brier 0.150, ECE 0.139.
- Delayed-recall predictions for vocabulary (FSRS retrievability at the delayed test vs the true recall probability): n=775, mean predicted 0.670, mean true 0.502, rank correlation 0.031.

Metric definitions are in `docs/adaptive-learning.md`. Immediate performance and delayed retention are measured separately: immediate = outcomes during sessions; delayed = true recall probability after the delay.
