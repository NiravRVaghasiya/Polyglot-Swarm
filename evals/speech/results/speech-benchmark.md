# Speech assessment benchmark

## speechocean762 — external, expert-labelled (English read-aloud, Mandarin-L1)

> Five experts' scores from the published corpus (CC BY 4.0). Learners are Mandarin-L1 children and adults reading English. These results do not transfer to other languages, L1s or free speech.

- Clips: {'dev': {'clips': 300, 'transcribed': 300, 'rejected': 0, 'skipped_no_speech': 0, 'failed': 0}, 'test': {'clips': 400, 'transcribed': 400, 'rejected': 0, 'skipped_no_speech': 0, 'failed': 0}}
- Corpus WER (Whisper base, test): 0.487
  - adult: corpus WER 0.508
  - child: corpus WER 0.461
  - female: corpus WER 0.415
  - male: corpus WER 0.550

### Fluency vs expert fluency (test)

- Scored by the shipped gates: 0.733 [0.687, 0.774] (293/400); abstained: {'low_confidence': 97, 'repetition_loop': 4, 'too_few_words': 6}
- Fitted map (speechocean762/train sample (n=232)) Spearman: 0.595 [0.507, 0.667] (n=293); MAE (0–10): 0.672 [0.611, 0.737] (n=293)
- Text-only baseline (reference length) Spearman: 0.128 [0.015, 0.234] (n=293); MAE: 0.893 [0.809, 0.973] (n=293)
- Constant baseline MAE: 0.847 [0.758, 0.932] (n=293)
- Expert fluency distribution: {'0': 0, '1': 0, '2': 0, '3': 2, '4': 1, '5': 3, '6': 12, '7': 46, '8': 100, '9': 103, '10': 26}
- Single measures vs expert fluency:
  - speech_rate_wpm: 0.525 [0.427, 0.606] (n=293)
  - pause_time_ratio: -0.059 [-0.192, 0.065] (n=293)
  - mean_length_of_run: -0.092 [-0.210, 0.031] (n=293)
  - repetitions: -0.121 [-0.226, -0.003] (n=293)
- Fluency map, adult: 0.659 [0.549, 0.753] (n=152)
- Fluency map, child: 0.416 [0.263, 0.553] (n=141)

### Intelligibility (ASR-recognised target words) vs experts (test)

- vs sentence accuracy: 0.514 [0.438, 0.588] (n=400)
- vs completeness: 0.080 [0.078, 0.155] (n=400)
- Words flagged 'not recognised', by expert word accuracy:
  - perfect: 0.236 [0.219, 0.254] (540/2287)
  - accented_correct: 0.500 [0.369, 0.631] (26/52)
  - mispronounced: 0.822 [0.763, 0.868] (166/202)
- False corrections (flagged words experts rated acceptable): 0.773 [0.742, 0.802] (566/732)
  - adult: perfect 0.204, accented_correct 0.393, mispronounced 0.819
  - child: perfect 0.275, accented_correct 0.625, mispronounced 0.830

### Pronunciation proxy gate (word probability vs expert word accuracy)

- dev: 0.371 [0.338, 0.404] (n=1927); test: 0.322 [0.292, 0.348] (n=2541); gate 0.35; passes on dev: True; on test: False

### Abstention quality

- transcript confidence vs utterance WER: -0.741 [-0.783, -0.690] (n=400)
- coverage at threshold 0.55: 0.748 [0.703, 0.788] (299/400)
- WER kept: 0.214 [0.184, 0.244] (n=299); WER abstained: 1.336 [0.804, 2.051] (n=101)
- recogniser repetition loops (dev+test): 0.007 [0.003, 0.017] (5/700), 5 of them above the confidence threshold (caught only by the compression-ratio gate)

Performance (CPU, Whisper base): {'latency_ms_p50': 5234.160899883136, 'latency_ms_p90': 6481.0401001013815, 'audio_s_p50': 3.51, 'real_time_factor_p50': 1.5187703736854468, 'cost_usd': 0.0, 'failure_rate': {'value': 0.0, 'ci95': [0.0, 0.005458046242222682], 'k': 0, 'n': 700}}

## Synthetic Spanish speech — SYNTHETIC (Edge TTS), no expert labels

> Native synthetic voices: every word is pronounced correctly, so this measures the recogniser and pipeline, not learners.

- WER by accent: {'Argentina': '0.111', 'Colombia': '0.101', 'Mexico': '0.038', 'Spain': '0.030'}
- WER by rate: {'+0%': '0.058', '+25%': '0.058'}
- WER by SNR: {'0 dB': '0.361', '10 dB': '0.056', '20 dB': '0.021', 'clean': '0.017'}
- False 'not intelligible' rate on correctly pronounced words, by accent:
  - Argentina: 0.097 [0.068, 0.137] (28/288)
  - Colombia: 0.090 [0.062, 0.129] (26/288)
  - Mexico: 0.031 [0.020, 0.049] (18/576)
  - Spain: 0.024 [0.015, 0.040] (14/576)
- Learner grammar errors kept by the recogniser: 0.861 [0.795, 0.908] (124/144); auto-corrected: 0.007 [0.001, 0.038] (1/144); other: 0.132 [0.086, 0.197] (19/144)
- Abstention: {'silence': {'clips': 4, 'no_graded_evidence': {'value': 1.0, 'ci95': [0.5100999795960008, 1.0], 'k': 4, 'n': 4}, 'transcribed_words': 0}, 'noise_only': {'clips': 4, 'no_graded_evidence': {'value': 1.0, 'ci95': [0.5100999795960008, 1.0], 'k': 4, 'n': 4}, 'transcribed_words': 0}}
- Noisy speech flagged 'noisy', by SNR: {'0 dB': '1.000', '10 dB': '0.000', '20 dB': '0.000'}
- Latency: {'latency_ms_p50': 5260.4016999248415, 'latency_ms_p90': 5657.261300133541}

## Formats and edge cases — SYNTHETIC (offline Windows TTS, English)

| format | decoded | median latency ms | mean WER |
|---|---|---|---|
| wav | 4/4 | 5227 | 0.000 |
| flac | 4/4 | 5167 | 0.000 |
| mp3 | 4/4 | 5155 | 0.000 |
| ogg | 4/4 | 5179 | 0.000 |
| webm | 4/4 | 5125 | 0.000 |
| mp4 | 4/4 | 5122 | 0.000 |

| edge case | accepted | code / issues |
|---|---|---|
| silence | True | ['no_speech_detected'] |
| clipped | True | ['clipped'] |
| too_short | False | too_short |
| too_long | False | too_long |
| truncated_webm | True | [] |
| mislabelled | False | format_mismatch |
| not_audio | False | unsupported_format |

No real learner study has been run. No Spanish expert-labelled audio exists in this project; the speechocean762 results are the only expert comparison.
