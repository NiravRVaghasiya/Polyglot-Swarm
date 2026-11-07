# Adaptive learning outcomes — policy simulation

> **Simulated learners.** Every number below comes from the simulator in `evals/adaptive/simulator.py` and reflects its assumptions. None of it is a real learner outcome.

- Generator: `continuous`, gain peak 0.7.
- 40 simulated learners, 20 sessions of 20.0 minutes; delayed tests at +30.0 days after the last session with no practice in between.
- Every policy faces the same learners with common random numbers; differences are paired per learner (bootstrap 95% CI).

| metric | static | existing_planner | adaptive | adaptive_predictive | adaptive_full |
|---|---|---|---|---|---|
| immediate_success | 0.658 [0.618, 0.699] | 0.621 [0.571, 0.672] | 0.775 [0.741, 0.803] | 0.740 [0.712, 0.766] | 0.706 [0.673, 0.738] |
| difficulty_adjusted_success | 0.164 [0.115, 0.213] | 0.150 [0.089, 0.211] | 0.261 [0.214, 0.302] | 0.188 [0.143, 0.235] | 0.195 [0.151, 0.239] |
| grammar_mastery_gain | 0.125 [0.111, 0.142] | 0.075 [0.059, 0.094] | 0.124 [0.107, 0.141] | 0.179 [0.157, 0.202] | 0.176 [0.157, 0.197] |
| grammar_recall_end | 0.652 [0.604, 0.700] | 0.602 [0.553, 0.657] | 0.650 [0.606, 0.698] | 0.706 [0.659, 0.754] | 0.703 [0.655, 0.752] |
| grammar_recall_delayed | 0.636 [0.589, 0.684] | 0.574 [0.526, 0.627] | 0.625 [0.579, 0.674] | 0.654 [0.606, 0.703] | 0.653 [0.606, 0.703] |
| knowledge_retention_ratio | 0.976 [0.970, 0.980] | 0.951 [0.943, 0.958] | 0.958 [0.949, 0.967] | 0.922 [0.911, 0.932] | 0.926 [0.912, 0.938] |
| objectives_completed_end | 0.497 [0.419, 0.578] | 0.422 [0.356, 0.494] | 0.544 [0.481, 0.608] | 0.631 [0.550, 0.708] | 0.628 [0.547, 0.703] |
| objectives_completed_delayed | 0.450 [0.372, 0.531] | 0.364 [0.294, 0.439] | 0.483 [0.411, 0.558] | 0.467 [0.389, 0.547] | 0.483 [0.397, 0.567] |
| words_introduced | 40.000 [40.000, 40.000] | 40.000 [40.000, 40.000] | 34.650 [33.550, 35.675] | 35.675 [34.375, 36.975] | 23.675 [22.075, 25.350] |
| words_recall_delayed | 0.458 [0.417, 0.504] | 0.432 [0.394, 0.476] | 0.484 [0.447, 0.526] | 0.476 [0.441, 0.516] | 0.579 [0.540, 0.618] |
| words_held_delayed | 4.475 [2.950, 6.175] | 4.250 [2.850, 5.950] | 4.950 [3.350, 6.775] | 4.975 [3.400, 6.825] | 6.000 [4.375, 7.850] |
| grammar_gain_per_hour | 0.192 [0.169, 0.217] | 0.110 [0.087, 0.137] | 0.172 [0.149, 0.195] | 0.251 [0.221, 0.283] | 0.249 [0.222, 0.278] |
| words_held_per_hour | 0.761 [0.501, 1.050] | 0.692 [0.463, 0.971] | 0.768 [0.520, 1.052] | 0.782 [0.532, 1.077] | 0.956 [0.697, 1.254] |
| recommendation_relevance | 0.913 [0.896, 0.930] | 0.818 [0.759, 0.871] | 0.972 [0.957, 0.983] | 0.968 [0.956, 0.979] | 0.969 [0.957, 0.980] |
| practice_minutes | 353.000 [353.000, 353.000] | 369.825 [368.575, 371.000] | 388.300 [385.750, 390.525] | 384.150 [382.125, 385.925] | 381.000 [378.875, 383.025] |

Paired differences against `existing_planner` (policy minus baseline):

| policy | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_held_delayed | grammar_gain_per_hour | recommendation_relevance |
|---|---|---|---|---|---|---|
| static | 0.037 [-0.011, 0.084] | 0.062 [0.051, 0.073] | 0.086 [0.044, 0.128] | 0.225 [0.025, 0.450] | 0.082 [0.064, 0.100] | 0.095 [0.040, 0.152] |
| adaptive | 0.154 [0.102, 0.210] | 0.051 [0.039, 0.062] | 0.119 [0.078, 0.161] | 0.700 [0.375, 1.050] | 0.062 [0.041, 0.083] | 0.154 [0.095, 0.219] |
| adaptive_predictive | 0.118 [0.070, 0.164] | 0.080 [0.063, 0.095] | 0.103 [0.044, 0.153] | 0.725 [0.425, 1.075] | 0.141 [0.113, 0.170] | 0.150 [0.095, 0.209] |
| adaptive_full | 0.084 [0.040, 0.131] | 0.079 [0.065, 0.093] | 0.119 [0.064, 0.169] | 1.750 [1.250, 2.225] | 0.139 [0.114, 0.166] | 0.151 [0.096, 0.208] |

Paired differences isolating one capability (policy minus its baseline):

| comparison | immediate_success | grammar_recall_delayed | objectives_completed_delayed | words_introduced | words_recall_delayed | words_held_delayed | words_held_per_hour | grammar_gain_per_hour |
|---|---|---|---|---|---|---|---|---|
| adaptive_vs_static | 0.117 [0.092, 0.142] | -0.011 [-0.020, -0.003] | 0.033 [-0.008, 0.075] | -5.350 [-6.475, -4.225] | 0.026 [0.017, 0.035] | 0.475 [0.225, 0.750] | 0.008 [-0.034, 0.048] | -0.020 [-0.038, -0.004] |
| prediction_and_difficulty | -0.035 [-0.059, -0.011] | 0.029 [0.017, 0.042] | -0.017 [-0.058, 0.022] | 1.025 [0.025, 1.900] | -0.008 [-0.014, -0.001] | 0.025 [-0.100, 0.150] | 0.014 [-0.012, 0.038] | 0.079 [0.055, 0.104] |
| fsrs_integration_vs_fsrs_only | -0.034 [-0.050, -0.020] | -0.001 [-0.009, 0.008] | 0.017 [-0.017, 0.053] | -12.000 [-13.075, -10.800] | 0.103 [0.089, 0.117] | 1.025 [0.650, 1.425] | 0.173 [0.116, 0.237] | -0.002 [-0.020, 0.017] |
| full_vs_static | 0.048 [0.026, 0.070] | 0.017 [0.007, 0.028] | 0.033 [-0.011, 0.075] | -16.325 [-17.975, -14.725] | 0.121 [0.104, 0.138] | 1.525 [1.050, 2.025] | 0.195 [0.119, 0.272] | 0.057 [0.039, 0.076] |

## Prediction accuracy inside the adaptive policy

- Next-attempt success predictions (made before each attempt): n=5526, AUC 0.751, log loss 0.500, Brier 0.161, ECE 0.090.
- Delayed-recall predictions for vocabulary (FSRS retrievability at the delayed test vs the true recall probability): n=930, mean predicted 0.714, mean true 0.604, rank correlation 0.578.

Metric definitions are in `docs/adaptive-learning.md`. Immediate performance and delayed retention are measured separately: immediate = outcomes during sessions; delayed = true recall probability after the delay.
