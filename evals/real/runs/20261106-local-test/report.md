# Real-model evaluation — run `20261106-local-test`

- **Run status:** complete
- **Synthetic:** no
- **Dataset:** grammar `grammar-2026.11.0` split `test` (65 cases, sha256 `77b12262dab8`), validation status {'author_labeled': 98}
- **Dataset:** vocabulary `vocabulary-2026.11.0` split `test` (11 cases, sha256 `ec5dd0a81900`), validation status {'author_labeled': 14}
- **Config hash:** `68921760d5b7`; git `127bd878e7` (dirty)
- **Prompts:** `grammar@1` (6ff501d281), `grammar_context@1` (66c0da6f92), `vocabulary@1` (b32f6a06e6)
- **Calibration maps fitted on dev run:** `20261106-local-dev`

## Providers

| provider | probe | state | ok / planned | failures |
|---|---|---|---|---|
| ollama:llama3.1:latest | available | complete | 81 / 81 | - |
| ollama:gemma2:2b | available | complete | 81 / 81 | - |
| ollama:granite3.2:2b | available | complete | 81 / 81 | - |

## ollama:gemma2:2b

### Grammar (production prompt `grammar@1`, case level, ambiguous excluded)

Confusion: {'tp': 32, 'fp': 19, 'fn': 3, 'tn': 9} over 63 labeled cases.

| metric | value [95% CI] (n) |
|---|---|
| precision | 0.627 [0.49, 0.75] (n=51) |
| recall | 0.914 [0.78, 0.97] (n=35) |
| false_correction_rate | 0.679 [0.49, 0.82] (n=28) |
| missed_error_rate | 0.086 [0.03, 0.22] (n=35) |
| accuracy | 0.651 [0.53, 0.76] (n=63) |
| localization_rate | 0.812 [0.65, 0.91] (n=32) |
| span_precision | 0.413 [0.30, 0.54] (n=63) |
| span_recall | 0.722 [0.56, 0.84] (n=36) |
| correction_accuracy | 0.654 [0.46, 0.81] (n=26) |
| construction_accuracy | 0.115 [0.04, 0.29] (n=26) |
| acceptable_alternative_recognition | 0.500 [0.09, 0.91] (n=2) |
| synonym_recognition | 1.000 [0.21, 1.00] (n=1) |
| dialect_acceptance | 0.250 [0.05, 0.70] (n=4) |
| register_acceptance | 0.125 [0.02, 0.47] (n=8) |
| register_label_agreement | 0.125 [0.02, 0.47] (n=8) |
| context_inappropriate_recall | 1.000 [0.51, 1.00] (n=4) |
| vocabulary_misuse_recall | 0.800 [0.38, 0.96] (n=5) |
| ambiguous_abstention_rate | 0.500 [0.09, 0.91] (n=2) |
| adversarial_accuracy | 1.000 [0.21, 1.00] (n=1) |
| f1 | 0.7442 [0.6329, 0.8372] (n=63) |

### Structured output

| metric | value [95% CI] (n) |
|---|---|
| execution_failure_rate | 0.000 [0.00, 0.06] (n=65) |
| json_valid_rate | 1.000 [0.94, 1.00] (n=65) |
| schema_valid_rate | 0.985 [0.92, 1.00] (n=65) |
| bare_list_rate | 0.000 [0.00, 0.06] (n=65) |
| recoverable_rate | 0.000 [0.00, 0.79] (n=1) |
| missing_field_rate | 0.247 [0.16, 0.35] (n=77) |
| invalid_field_rate | 0.000 [0.00, 0.05] (n=77) |
| unsupported_assessment_rate | 0.000 [0.00, 0.05] (n=77) |

Missing fields: {'construction': 18, 'classification': 18, 'severity': 18, 'confidence': 18, 'original': 1, 'correction': 1}

### Evidence extraction (production pipeline)

| metric | value |
|---|---|
| precision | 0.413 [0.30, 0.54] (n=63) |
| recall | 0.722 [0.56, 0.84] (n=36) |
| skill_classification_accuracy | 0.731 [0.54, 0.86] (n=26) |
| subskill_classification_accuracy | 0.115 [0.04, 0.29] (n=26) |
| difficulty_known_rate | 0.192 [0.09, 0.38] (n=26) |
| difficulty_classification_accuracy | 0.500 [0.15, 0.85] (n=4) |
| duplicate_case_distinct_errors_recovered | 0.500 [0.09, 0.91] (n=2) |
| duplicate_events_after_pipeline | 0 |

Skill accuracy by expected skill: grammar: 1.000 [0.83, 1.00] (n=19), pragmatics: 0.000 [0.00, 0.56] (n=3), vocabulary: 0.000 [0.00, 0.49] (n=4)

### Confidence calibration

- raw LLM: n=45, mean confidence 0.5822, accuracy 0.556 [0.41, 0.69] (n=45), ECE 0.0489 [0.0244, 0.2022], Brier 0.2476, AURC 0.4101, distinct confidence values 3
- pipeline: n=62, mean confidence 0.6968, accuracy 0.419 [0.30, 0.54] (n=62), ECE 0.2935 [0.2048, 0.4629], Brier 0.4377, AURC 0.7046, distinct confidence values 4
- raw confidence missing: 0.274 [0.18, 0.40] (n=62)
- Platt map (dev n=38) on test: ECE 0.0708, Brier 0.203; histogram: ECE 0.0323, Brier 0.2265
- committed map (platt, fitted on dev run 20261106-local-dev, n=38), applied offline to this run: ECE 0.2935 -> 0.0708; false-correction rate 0.679 [0.49, 0.82] (n=28) -> 0.464 [0.30, 0.64] (n=28); precision 0.627 [0.49, 0.75] (n=51) -> 0.629 [0.46, 0.77] (n=35); recall 0.914 [0.78, 0.97] (n=35) -> 0.629 [0.46, 0.77] (n=35)
- learner-model input: unweighted precision 0.4194, confidence-weighted 0.3727 (difference -0.0467, 95% CI [-0.0809, -0.0089])

### Detection accuracy by language

| segment | accuracy [95% CI] (n) |
|---|---|
| French | 0.500 [0.22, 0.78] (n=8) |
| German | 0.833 [0.44, 0.97] (n=6) |
| Italian | 0.600 [0.31, 0.83] (n=10) |
| Polish | 0.500 [0.15, 0.85] (n=4) |
| Spanish | 0.686 [0.52, 0.81] (n=35) |

### Detection accuracy by cefr

| segment | accuracy [95% CI] (n) |
|---|---|
| A1 | 0.769 [0.50, 0.92] (n=13) |
| A2 | 0.611 [0.39, 0.80] (n=18) |
| B1 | 0.652 [0.45, 0.81] (n=23) |
| B2 | 0.571 [0.25, 0.84] (n=7) |
| C1 | 0.500 [0.09, 0.91] (n=2) |

### Detection accuracy by difficulty

| segment | accuracy [95% CI] (n) |
|---|---|
| easy | 0.654 [0.46, 0.81] (n=26) |
| hard | 0.833 [0.44, 0.97] (n=6) |
| medium | 0.613 [0.44, 0.76] (n=31) |

### Detection accuracy by category

| segment | accuracy [95% CI] (n) |
|---|---|
| acceptable_alternative | 0.500 [0.09, 0.91] (n=2) |
| adversarial | 1.000 [0.21, 1.00] (n=1) |
| context_inappropriate | 1.000 [0.51, 1.00] (n=4) |
| correct | 0.429 [0.21, 0.67] (n=14) |
| formal | 0.000 [0.00, 0.79] (n=1) |
| incorrect | 0.920 [0.75, 0.98] (n=25) |
| informal | 0.143 [0.03, 0.51] (n=7) |
| regional | 0.250 [0.05, 0.70] (n=4) |
| vocabulary_misuse | 0.800 [0.38, 0.96] (n=5) |

Latency p50/p90/max: 61306.6/82611.2/91447.7 ms; tokens in/out 34224/7269 (estimated share 0.000 [0.00, 0.06] (n=65)); estimated cost $0.0

### Vocabulary extraction

| metric | value [95% CI] (n) |
|---|---|
| execution_failure_rate | 0.000 [0.00, 0.26] (n=11) |
| schema_valid_rate | 0.909 [0.62, 0.98] (n=11) |
| missing_field_rate | 0.000 [0.00, 0.09] (n=39) |
| precision | 0.795 [0.64, 0.89] (n=39) |
| recall | 0.655 [0.47, 0.80] (n=29) |
| forbidden_rate | 0.103 [0.04, 0.24] (n=39) |
| translation_accuracy | 1.000 [0.83, 1.00] (n=19) |
| produced_vs_exposed_accuracy | 1.000 [0.83, 1.00] (n=19) |
| nothing_to_extract_clean | 0.000 [0.00, 0.79] (n=1) |

## ollama:granite3.2:2b

### Grammar (production prompt `grammar@1`, case level, ambiguous excluded)

Confusion: {'tp': 16, 'fp': 9, 'fn': 19, 'tn': 19} over 63 labeled cases.

| metric | value [95% CI] (n) |
|---|---|
| precision | 0.640 [0.45, 0.80] (n=25) |
| recall | 0.457 [0.30, 0.62] (n=35) |
| false_correction_rate | 0.321 [0.18, 0.51] (n=28) |
| missed_error_rate | 0.543 [0.38, 0.70] (n=35) |
| accuracy | 0.556 [0.43, 0.67] (n=63) |
| localization_rate | 1.000 [0.81, 1.00] (n=16) |
| span_precision | 0.516 [0.35, 0.68] (n=31) |
| span_recall | 0.444 [0.30, 0.60] (n=36) |
| correction_accuracy | 0.625 [0.39, 0.82] (n=16) |
| construction_accuracy | 0.062 [0.01, 0.28] (n=16) |
| acceptable_alternative_recognition | 1.000 [0.34, 1.00] (n=2) |
| synonym_recognition | 1.000 [0.21, 1.00] (n=1) |
| dialect_acceptance | 0.250 [0.05, 0.70] (n=4) |
| register_acceptance | 0.750 [0.41, 0.93] (n=8) |
| register_label_agreement | 0.375 [0.14, 0.69] (n=8) |
| context_inappropriate_recall | 0.500 [0.15, 0.85] (n=4) |
| vocabulary_misuse_recall | 0.200 [0.04, 0.62] (n=5) |
| ambiguous_abstention_rate | 0.500 [0.09, 0.91] (n=2) |
| adversarial_accuracy | 0.000 [0.00, 0.79] (n=1) |
| f1 | 0.5333 [0.3704, 0.6765] (n=63) |

### Structured output

| metric | value [95% CI] (n) |
|---|---|
| execution_failure_rate | 0.000 [0.00, 0.06] (n=65) |
| json_valid_rate | 0.939 [0.85, 0.98] (n=65) |
| schema_valid_rate | 0.846 [0.74, 0.91] (n=65) |
| bare_list_rate | 0.092 [0.04, 0.19] (n=65) |
| recoverable_rate | 0.000 [0.00, 0.28] (n=10) |
| missing_field_rate | 0.068 [0.03, 0.14] (n=88) |
| invalid_field_rate | 0.011 [0.00, 0.06] (n=88) |
| unsupported_assessment_rate | 0.011 [0.00, 0.06] (n=88) |

Missing fields: {'original': 6, 'correction': 6, 'construction': 6, 'classification': 6, 'severity': 6, 'confidence': 6}

### Evidence extraction (production pipeline)

| metric | value |
|---|---|
| precision | 0.516 [0.35, 0.68] (n=31) |
| recall | 0.444 [0.30, 0.60] (n=36) |
| skill_classification_accuracy | 0.812 [0.57, 0.93] (n=16) |
| subskill_classification_accuracy | 0.062 [0.01, 0.28] (n=16) |
| difficulty_known_rate | 0.375 [0.18, 0.61] (n=16) |
| difficulty_classification_accuracy | 0.500 [0.15, 0.85] (n=4) |
| duplicate_case_distinct_errors_recovered | 0.000 [0.00, 0.66] (n=2) |
| duplicate_events_after_pipeline | 0 |

Skill accuracy by expected skill: grammar: 1.000 [0.77, 1.00] (n=13), pragmatics: 0.000 [0.00, 0.66] (n=2), vocabulary: 0.000 [0.00, 0.79] (n=1)

### Confidence calibration

- raw LLM: n=34, mean confidence 0.8735, accuracy 0.471 [0.31, 0.63] (n=34), ECE 0.4029 [0.25, 0.5618], Brier 0.4003, AURC 0.4637, distinct confidence values 2
- pipeline: n=34, mean confidence 0.8735, accuracy 0.471 [0.31, 0.63] (n=34), ECE 0.4029 [0.25, 0.5618], Brier 0.4003, AURC 0.4637, distinct confidence values 2
- raw confidence missing: 0.000 [0.00, 0.10] (n=34)
- fitted calibration: no_dev_run {'status': 'no_dev_run'}
- committed calibration map: absent
- learner-model input: unweighted precision 0.5333, confidence-weighted 0.5379 (difference 0.0045, 95% CI [-0.0037, 0.0125])

### Detection accuracy by language

| segment | accuracy [95% CI] (n) |
|---|---|
| French | 0.625 [0.31, 0.86] (n=8) |
| German | 0.500 [0.19, 0.81] (n=6) |
| Italian | 0.500 [0.24, 0.76] (n=10) |
| Polish | 0.750 [0.30, 0.95] (n=4) |
| Spanish | 0.543 [0.38, 0.70] (n=35) |

### Detection accuracy by cefr

| segment | accuracy [95% CI] (n) |
|---|---|
| A1 | 0.769 [0.50, 0.92] (n=13) |
| A2 | 0.611 [0.39, 0.80] (n=18) |
| B1 | 0.391 [0.22, 0.59] (n=23) |
| B2 | 0.571 [0.25, 0.84] (n=7) |
| C1 | 0.500 [0.09, 0.91] (n=2) |

### Detection accuracy by difficulty

| segment | accuracy [95% CI] (n) |
|---|---|
| easy | 0.731 [0.54, 0.86] (n=26) |
| hard | 0.500 [0.19, 0.81] (n=6) |
| medium | 0.419 [0.26, 0.59] (n=31) |

### Detection accuracy by category

| segment | accuracy [95% CI] (n) |
|---|---|
| acceptable_alternative | 1.000 [0.34, 1.00] (n=2) |
| adversarial | 0.000 [0.00, 0.79] (n=1) |
| context_inappropriate | 0.500 [0.15, 0.85] (n=4) |
| correct | 0.714 [0.45, 0.88] (n=14) |
| formal | 0.000 [0.00, 0.79] (n=1) |
| incorrect | 0.520 [0.34, 0.70] (n=25) |
| informal | 0.857 [0.49, 0.97] (n=7) |
| regional | 0.250 [0.05, 0.70] (n=4) |
| vocabulary_misuse | 0.200 [0.04, 0.62] (n=5) |

Latency p50/p90/max: 51892.0/89053.0/149660.9 ms; tokens in/out 36719/10536 (estimated share 0.000 [0.00, 0.06] (n=65)); estimated cost $0.0

### Vocabulary extraction

| metric | value [95% CI] (n) |
|---|---|
| execution_failure_rate | 0.000 [0.00, 0.26] (n=11) |
| schema_valid_rate | 0.364 [0.15, 0.65] (n=11) |
| missing_field_rate | 0.000 [0.00, 0.30] (n=9) |
| precision | 1.000 [0.70, 1.00] (n=9) |
| recall | 0.172 [0.08, 0.35] (n=29) |
| forbidden_rate | 0.000 [0.00, 0.30] (n=9) |
| translation_accuracy | 1.000 [0.57, 1.00] (n=5) |
| produced_vs_exposed_accuracy | 1.000 [0.57, 1.00] (n=5) |
| nothing_to_extract_clean | 1.000 [0.21, 1.00] (n=1) |

## ollama:llama3.1:latest

### Grammar (production prompt `grammar@1`, case level, ambiguous excluded)

Confusion: {'tp': 5, 'fp': 3, 'fn': 30, 'tn': 25} over 63 labeled cases.

| metric | value [95% CI] (n) |
|---|---|
| precision | 0.625 [0.31, 0.86] (n=8) |
| recall | 0.143 [0.06, 0.29] (n=35) |
| false_correction_rate | 0.107 [0.04, 0.27] (n=28) |
| missed_error_rate | 0.857 [0.71, 0.94] (n=35) |
| accuracy | 0.476 [0.36, 0.60] (n=63) |
| localization_rate | 0.800 [0.38, 0.96] (n=5) |
| span_precision | 0.500 [0.24, 0.76] (n=10) |
| span_recall | 0.139 [0.06, 0.29] (n=36) |
| correction_accuracy | 0.000 [0.00, 0.43] (n=5) |
| construction_accuracy | 0.600 [0.23, 0.88] (n=5) |
| acceptable_alternative_recognition | 0.500 [0.09, 0.91] (n=2) |
| synonym_recognition | 1.000 [0.21, 1.00] (n=1) |
| dialect_acceptance | 1.000 [0.51, 1.00] (n=4) |
| register_acceptance | 0.875 [0.53, 0.98] (n=8) |
| register_label_agreement | 0.000 [0.00, 0.32] (n=8) |
| context_inappropriate_recall | 0.500 [0.15, 0.85] (n=4) |
| vocabulary_misuse_recall | 0.000 [0.00, 0.43] (n=5) |
| ambiguous_abstention_rate | 1.000 [0.34, 1.00] (n=2) |
| adversarial_accuracy | 0.000 [0.00, 0.79] (n=1) |
| f1 | 0.2326 [0.0541, 0.4] (n=63) |

### Structured output

| metric | value [95% CI] (n) |
|---|---|
| execution_failure_rate | 0.000 [0.00, 0.06] (n=65) |
| json_valid_rate | 0.954 [0.87, 0.98] (n=65) |
| schema_valid_rate | 0.123 [0.06, 0.22] (n=65) |
| bare_list_rate | 0.831 [0.72, 0.90] (n=65) |
| recoverable_rate | 0.947 [0.86, 0.98] (n=57) |
| missing_field_rate | 0.000 [0.00, 0.05] (n=78) |
| invalid_field_rate | 0.000 [0.00, 0.05] (n=78) |
| unsupported_assessment_rate | 0.000 [0.00, 0.05] (n=78) |

Bare-list sensitivity (diagnostic, not app behaviour): wrapping 54 recoverable bare-list answers as `{"errors": [...]}` gives confusion {'tp': 29, 'fp': 21, 'fn': 6, 'tn': 7}, recall 0.829 [0.67, 0.92] (n=35), false_correction_rate 0.750 [0.57, 0.87] (n=28), accuracy 0.571 [0.45, 0.69] (n=63).

### Evidence extraction (production pipeline)

| metric | value |
|---|---|
| precision | 0.500 [0.24, 0.76] (n=10) |
| recall | 0.139 [0.06, 0.29] (n=36) |
| skill_classification_accuracy | 0.800 [0.38, 0.96] (n=5) |
| subskill_classification_accuracy | 0.600 [0.23, 0.88] (n=5) |
| difficulty_known_rate | 0.400 [0.12, 0.77] (n=5) |
| difficulty_classification_accuracy | 0.000 [0.00, 0.66] (n=2) |
| duplicate_case_distinct_errors_recovered | 1.000 [0.34, 1.00] (n=2) |
| duplicate_events_after_pipeline | 0 |

Skill accuracy by expected skill: grammar: 1.000 [0.51, 1.00] (n=4), pragmatics: 0.000 [0.00, 0.79] (n=1)

### Confidence calibration

- raw LLM: n=10, mean confidence 0.96, accuracy 0.500 [0.24, 0.76] (n=10), ECE 0.46 [0.18, 0.75], Brier 0.426, AURC 0.3389, distinct confidence values 3
- pipeline: n=10, mean confidence 0.96, accuracy 0.500 [0.24, 0.76] (n=10), ECE 0.46 [0.18, 0.75], Brier 0.426, AURC 0.3389, distinct confidence values 3
- raw confidence missing: 0.000 [0.00, 0.28] (n=10)
- fitted calibration: insufficient_dev_data {'status': 'insufficient_dev_data', 'dev_predictions': 9, 'required': 15}
- committed calibration map: insufficient_dev_data
- learner-model input: unweighted precision 0.5, confidence-weighted 0.5208 (difference 0.0208, 95% CI [0.0, 0.0383])

### Detection accuracy by language

| segment | accuracy [95% CI] (n) |
|---|---|
| French | 0.375 [0.14, 0.69] (n=8) |
| German | 0.500 [0.19, 0.81] (n=6) |
| Italian | 0.600 [0.31, 0.83] (n=10) |
| Polish | 0.500 [0.15, 0.85] (n=4) |
| Spanish | 0.457 [0.30, 0.62] (n=35) |

### Detection accuracy by cefr

| segment | accuracy [95% CI] (n) |
|---|---|
| A1 | 0.385 [0.18, 0.64] (n=13) |
| A2 | 0.667 [0.44, 0.84] (n=18) |
| B1 | 0.435 [0.26, 0.63] (n=23) |
| B2 | 0.286 [0.08, 0.64] (n=7) |
| C1 | 0.500 [0.09, 0.91] (n=2) |

### Detection accuracy by difficulty

| segment | accuracy [95% CI] (n) |
|---|---|
| easy | 0.538 [0.35, 0.71] (n=26) |
| hard | 0.500 [0.19, 0.81] (n=6) |
| medium | 0.419 [0.26, 0.59] (n=31) |

### Detection accuracy by category

| segment | accuracy [95% CI] (n) |
|---|---|
| acceptable_alternative | 0.500 [0.09, 0.91] (n=2) |
| adversarial | 0.000 [0.00, 0.79] (n=1) |
| context_inappropriate | 0.500 [0.15, 0.85] (n=4) |
| correct | 0.929 [0.69, 0.99] (n=14) |
| formal | 1.000 [0.21, 1.00] (n=1) |
| incorrect | 0.120 [0.04, 0.30] (n=25) |
| informal | 0.857 [0.49, 0.97] (n=7) |
| regional | 1.000 [0.51, 1.00] (n=4) |
| vocabulary_misuse | 0.000 [0.00, 0.43] (n=5) |

Latency p50/p90/max: 64334.8/124045.1/185883.4 ms; tokens in/out 33709/9366 (estimated share 0.000 [0.00, 0.06] (n=65)); estimated cost $0.0

### Vocabulary extraction

| metric | value [95% CI] (n) |
|---|---|
| execution_failure_rate | 0.000 [0.00, 0.26] (n=11) |
| schema_valid_rate | 1.000 [0.74, 1.00] (n=11) |
| missing_field_rate | 0.000 [0.00, 0.13] (n=25) |
| precision | 0.920 [0.75, 0.98] (n=25) |
| recall | 0.586 [0.41, 0.74] (n=29) |
| forbidden_rate | 0.080 [0.02, 0.25] (n=25) |
| translation_accuracy | 1.000 [0.82, 1.00] (n=17) |
| produced_vs_exposed_accuracy | 1.000 [0.82, 1.00] (n=17) |
| nothing_to_extract_clean | 0.000 [0.00, 0.79] (n=1) |

## Cross-provider comparison (`grammar@1`)

| providers | agreement | kappa | McNemar (a only / b only, p) |
|---|---|---|---|
| ollama:gemma2:2b vs ollama:granite3.2:2b | 0.569 [0.45, 0.68] (n=65) | 0.2308 | 17 / 11, p=0.3449 |
| ollama:gemma2:2b vs ollama:llama3.1:latest | 0.323 [0.22, 0.44] (n=65) | 0.0678 | 27 / 16, p=0.1263 |
| ollama:granite3.2:2b vs ollama:llama3.1:latest | 0.477 [0.36, 0.60] (n=65) | -0.2319 | 19 / 14, p=0.4869 |

Disagreements by category: {'acceptable_alternative': 1, 'adversarial': 1, 'ambiguous': 1, 'context_inappropriate': 4, 'correct': 9, 'formal': 1, 'incorrect': 23, 'informal': 6, 'regional': 3, 'vocabulary_misuse': 4}

Cases every provider got wrong:
- `es-003` (incorrect): La casa es muy blanco.
- `fr-008` (vocabulary_misuse): J'ai acheté ce roman à la bibliothèque du quartier pour quinze euros.
- `it-008` (incorrect): Mi piace molto i libri di storia.

## Prompt variants (paired, cases with a situational context)

| provider | variant | n | baseline acc | variant acc | McNemar p |
|---|---|---|---|---|---|
| ollama:gemma2:2b | grammar_context@1 | 5 | 0.800 [0.38, 0.96] (n=5) | 0.800 [0.38, 0.96] (n=5) | 1.0 |
| ollama:granite3.2:2b | grammar_context@1 | 5 | 0.600 [0.23, 0.88] (n=5) | 0.600 [0.23, 0.88] (n=5) | 1.0 |
| ollama:llama3.1:latest | grammar_context@1 | 5 | 0.600 [0.23, 0.88] (n=5) | 0.200 [0.04, 0.62] (n=5) | 0.5 |

## Quality gates

> The benchmark datasets are not expert-validated (author_labeled), so these gate decisions are provisional and must not be used to approve a model for production learner assessment.

| provider | metric | threshold | value [95% CI] | decision |
|---|---|---|---|---|
| ollama:gemma2:2b | grammar.false_correction_rate | <= 0.1 | 0.6786 [0.4934, 0.8207] | fail |
| ollama:gemma2:2b | grammar.recall | >= 0.6 | 0.9143 [0.7762, 0.9704] | pass |
| ollama:gemma2:2b | structured.schema_valid_rate | >= 0.95 | 0.9846 [0.9179, 0.9973] | inconclusive |
| ollama:granite3.2:2b | grammar.false_correction_rate | <= 0.1 | 0.3214 [0.1793, 0.5066] | fail |
| ollama:granite3.2:2b | grammar.recall | >= 0.6 | 0.4571 [0.3047, 0.6181] | inconclusive |
| ollama:granite3.2:2b | structured.schema_valid_rate | >= 0.95 | 0.8462 [0.7394, 0.9142] | fail |
| ollama:llama3.1:latest | grammar.false_correction_rate | <= 0.1 | 0.1071 [0.0371, 0.272] | inconclusive |
| ollama:llama3.1:latest | grammar.recall | >= 0.6 | 0.1429 [0.0626, 0.2938] | fail |
| ollama:llama3.1:latest | structured.schema_valid_rate | >= 0.95 | 0.1231 [0.0637, 0.2245] | fail |
