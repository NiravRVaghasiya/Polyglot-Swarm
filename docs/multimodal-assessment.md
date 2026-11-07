# Multimodal assessment (speech first)

How Polyglot Swarm assesses speaking and listening from audio, how it turns
the results into learner-model evidence, and how this was evaluated. The
design decision is [ADR-0034](adr/0034-multimodal-assessment.md).

## Pipeline

```
upload ─► ingest ─► gate ─► transcribe ─► assess ─► evidence ─► LKM / planner
          (validate,  (silence,  (Whisper,     (fluency,   (typed events,
           decode,     language)  timing,       intelligibility, provenance,
           quality)               confidence)   pronunciation,   uncertainty)
                                                spoken grammar)
```

Each stage is a separate module, and each records a `ProcessingStep`: stage,
provider, model, latency, attempts, status and error category. The
`AssessmentReport` returns every step, so a partial result (for example,
ingestion succeeded but transcription failed) is still useful and honest.

| Module | Stage |
|---|---|
| `src/multimodal/contracts.py` | modality-neutral types and stage protocols |
| `src/multimodal/audio.py` | ingestion: format sniffing, limits, decoding, signal quality |
| `src/multimodal/transcription.py` | speech-to-text provider protocol, local Whisper, retries |
| `src/multimodal/speaking.py` | fluency, intelligibility, pronunciation (with abstention) |
| `src/multimodal/listening.py` | listening tasks and scoring |
| `src/multimodal/evidence.py` | mapping to LKM evidence |
| `src/multimodal/pipeline.py` | orchestration |
| `src/multimodal/store.py` | submissions, retention, deletion |
| `src/api/routes/assessment_routes.py` | API |

A new modality adds an ingestor and processors that produce `Observation`s,
plus assessors that return `DimensionResult`s. Evidence mapping and the LKM
are unchanged.

### Ingestion

| Rule | Value / behaviour |
|---|---|
| Formats | wav, webm, ogg (incl. opus), mp3, mp4/m4a (aac), flac — sniffed from magic bytes |
| Declared vs actual format | mismatch → `422 format_mismatch` |
| Size | ≤ 10 MB (`413 too_large`) |
| Duration | 0.3 s – 120 s (`too_short` / `413 too_long`) |
| Decoding | 16 kHz mono PCM via ffmpeg (30 s timeout); without ffmpeg only 16 kHz mono PCM WAV works (`503 decoder_unavailable`) |
| Unrecognised data | `415 unsupported_format`; undecodable → `422 undecodable` |
| Quality flags (accepted, not rejected) | `no_speech_detected` (≤ −55 dBFS, or < 5% active frames), `noisy` (estimated SNR < 10 dB), `clipped` (> 1% samples at full scale) |

### Speech recognition

`WhisperLocalProvider` (openai-whisper, the `voice` extra) keeps:

- segments;
- word timestamps and word probabilities;
- the detected language and its probability.

**Transcription confidence** is the duration-weighted mean word
probability. It describes the recogniser, not the learner.

The gates that run around the recogniser:

| Situation | Behaviour |
|---|---|
| No speech detected | the recogniser is not run (Whisper invents text on silence) |
| A segment Whisper itself marks as non-speech (`no_speech_prob > 0.6` and `avg_logprob < −1`) | dropped |
| A different language detected with p ≥ 0.6 | the assessment abstains (`language_mismatch`) |
| A language that is not supported | the assessment abstains |
| A repetition loop (text compression ratio > 2.4, Whisper's own threshold) | the assessment abstains (`repetition_loop`); confidence does not catch these |
| Transient provider error | retried once |
| `unavailable` / `unsupported_language` | not retried, and no other provider is substituted |

**Accents, dialects and multiple speakers.** Accent and dialect are never
assessed as such, but the recogniser is **not accent-neutral** (see
[Results](#results)): it misses correctly pronounced words more often for
some accents and for children. That is why intelligibility gives no
word-level corrections and carries low confidence. Multiple speakers are
**not detected**: there is no diarization. The assessment assumes a single-speaker recording from the
learner's microphone. This is a documented limitation.

### Speaking dimensions

Every dimension has a `basis` (`timing`, `transcript`, `acoustic_proxy`,
`response`), a status (`ok`, `partial`, `abstained`), a confidence, its raw
measures, and feedback linked to time spans.

| Dimension | Basis | What it is | Abstains when |
|---|---|---|---|
| `fluency` | timing | observable measures: speech rate, articulation rate, silent pauses (≥ 0.25 s; long ≥ 1 s), pause-time ratio, mean length of run, repetitions, filled pauses. A logistic map fitted on expert fluency ratings gives a 0–1 value **for English read-aloud only**; elsewhere the result is `partial` (measures, no score). | no speech; fewer than 4 words; no word timing; transcript confidence < 0.55 |
| `intelligibility` | transcript | share of a read-aloud target's words that the recogniser heard as those words, with diacritics and case normalised. Intelligibility *to an ASR model*, **not phonetic accuracy**. Feedback is one neutral note; no word is named as wrong. | not a read-aloud task; noisy audio; low transcript confidence and words missed |
| `pronunciation` | acoustic proxy | mean word probability on target words. **Assessed only for languages in `PRONUNCIATION_VALIDATED`.** | always, outside validated languages |
| `spoken_grammar` | transcript | the existing grammar agent on the transcript of *free speech* | read-aloud tasks (the learner did not choose the words); transcript confidence < 0.75 |

`confidence` on a dimension is the reliability of the *judgment* and does
not include transcription confidence (that travels separately, so it is
never counted twice):

| Dimension | Confidence |
|---|---|
| fluency (English read-aloud) | 0.6, halved for noisy audio |
| intelligibility | 0.5 for English (moderate agreement with experts), 0.3 elsewhere |
| pronunciation proxy | 0.4, if a language is ever validated |

Whisper's word timing is approximate, about ±0.1–0.3 s.

### Listening

Learners hear a synthesised stimulus. The voice, accent, speech rate and
style are task metadata. They answer by **choosing or typing**, so listening
scores never depend on speech recognition or on speaking ability.

| Question kind | What it measures |
|---|---|
| `recognition` | identify what was said |
| `comprehension` | understand the meaning |
| `recall` | reproduce content from memory |

Free text is matched ignoring case and accents, with a small typo tolerance,
because recall tests listening, not spelling.

Task difficulty is the script's CEFR difficulty, adjusted ±0.05 for fast or
slow speech.

The bank (`src/multimodal/listening_bank/spanish.yaml`, 8 tasks, A1–B2, five
regional voices, three rates) is **author-written, not expert-validated**.

### Evidence and the learner model

Evidence schema v3 (migration 0009) adds four fields:

| Field | Content |
|---|---|
| `modality` | `"text"` (default for old rows) or `"audio"` |
| `media_ref` | asset id, submission id and, when known, the time span |
| `processing` | the stages, providers, models and latencies |
| `transcription_confidence` | the recogniser's confidence, kept separate from `confidence` (the evaluator's confidence about the learner) |

The rules that govern these events:

- **Skill mapping:**

  | Dimension | Skill and subskill |
  |---|---|
  | fluency | `speaking` / `fluency` |
  | intelligibility | `pronunciation` / `intelligibility` |
  | pronunciation proxy | `pronunciation` / `acoustic_proxy` |
  | listening questions | `listening` / `recognition`, `comprehension` or `recall` |

- **Two uncertainties.** The learner model (`lkm-evidence-v2`) multiplies
  `confidence` (judgment reliability only) by `transcription_confidence`
  for transcript-derived evidence. An uncertain recording counts *less*; it is never read as low
  ability.
- **Scored outcomes.** The `scored` assessment carries a continuous outcome
  in `payload.score`.
- **No double counting.** One event per assessed dimension per submission.
  All events from one recording share `correlation_id = audio:<hash>` and
  `item_id = utterance:<hash>`, so resubmitting the same audio is one
  observation.
- **Exposure is not competence.** Measures without a validated score are
  recorded as `exposed`: practice coverage, never mastery. Abstained
  dimensions emit nothing.
- **No transcript text in evidence.** The transcript lives only in the
  submission record.
- **Planner.** The Phase 3 planner proposes `speaking_check` (skill
  `speaking`) and `read_aloud` (skill `pronunciation`) alongside
  `listening_check`. A single noisy observation is down-weighted by its
  transcription confidence. It also goes through the existing bounded
  estimation and difficulty rules (ADR-0033), so it cannot cause an abrupt
  change.

## Privacy, retention and access

| Data | Kept? | Where | Deleted by |
|---|---|---|---|
| Raw audio | **No**, by default. It is decoded in memory and written to a temp file only for the recogniser, then deleted. | — | — |
| Raw audio with consent (`retain_audio: true`) | at most 30 days | `<data_dir>/media/<user>/` | `purge_expired` (runs on every submission), submission delete, account delete |
| Transcript, measures, feedback | yes | `media_submissions.report` | `DELETE /api/v1/assessment/submissions/{id}`, account delete |
| Evidence (scores and measures, no transcript) | yes, as learning history | `evidence` | account delete |

- **Access.** Every route is authenticated, and every query is scoped to the
  caller's user id. The response never includes server file paths.
- **Logging.** Logs record ids, sizes, formats, durations and statuses,
  never audio bytes or transcript text. A test checks this.
- **Export.** Privacy export includes `media_submissions`.
- **Provider calls.**
  - The recogniser runs locally, so no audio leaves the server.
  - Listening stimuli are synthesised by Edge TTS (a Microsoft service).
    Only the task's own script text is sent; no learner data is.

## Evaluation

```bash
python -m evals.speech speechocean        # external, expert-labelled (download first)
python -m evals.speech synthetic-build    # synthetic Spanish (Edge TTS, network)
python -m evals.speech synthetic
python -m evals.speech formats            # offline formats/edge cases (Windows)
python -m evals.speech report             # -> evals/speech/results/speech-benchmark.md
```

**speechocean762** (download it to `evals/speech/external/speechocean762`):

- source: <https://www.openslr.org/101/>;
- about 520 MB, CC BY 4.0;
- the archive is extracted in place and not committed.

Results are in the next section; the full generated report is
[`evals/speech/results/speech-benchmark.md`](../evals/speech/results/speech-benchmark.md).
Three kinds of data are kept apart and labelled as such:

| Data | Labels | Measures |
|---|---|---|
| speechocean762 | external, **expert-labelled** (5 experts) | transcription; fluency, intelligibility and the pronunciation proxy against experts; abstention; subgroups |
| Synthetic Spanish (Edge TTS) | **synthetic**, no expert labels | recogniser robustness by accent, rate and noise; accent fairness on correct speech; error preservation; abstention |
| Offline English TTS | **synthetic** | format support, latency, edge cases |

No real learner study has been run, and no Spanish expert-labelled audio
exists.

## Results

Recogniser: local Whisper `base` on CPU, run on 2026-11-07. Samples are
deterministic and age-balanced: speechocean762 dev = 300 clips from the
train split (used for fitting), test = 400 clips from the test split
(reported). Intervals are 95% (bootstrap for correlations and means, Wilson
for proportions). Where a metric depends on a gate, it is computed with the
shipped gates.

### Expert-labelled: speechocean762 (English read-aloud, Mandarin-L1)

| Measure | Result | Reading |
|---|---|---|
| Corpus WER (test) | 0.487 (adults 0.508, children 0.461; female 0.415, male 0.550) | Whisper base recognises non-native read speech poorly; WER here mixes recogniser and learner errors |
| Transcript confidence vs utterance WER | Spearman −0.741 [−0.783, −0.690] | confidence is a useful abstention signal |
| Abstention at confidence 0.55 + loop gate | 74.8% kept; WER kept 0.214 [0.184, 0.244] vs abstained 1.336 | abstention removes most bad transcripts |
| Repetition loops | 5 / 700 clips (0.7%), **all above the confidence threshold** | caught only by the compression-ratio gate, added after this run |
| **Fluency map** vs expert fluency | Spearman 0.595 [0.507, 0.667]; MAE 0.67 / 10 [0.61, 0.74] (n=293, 73% coverage) | clearly better than the baselines below |
| Text-only baseline (sentence length) | Spearman 0.128 [0.015, 0.234]; MAE 0.89 | |
| Constant baseline | MAE 0.85 [0.76, 0.93] | |
| Fluency map by age | adults 0.659 [0.549, 0.753]; children 0.416 [0.263, 0.553] | **much weaker for children** |
| Intelligibility vs expert sentence accuracy | Spearman 0.514 [0.438, 0.588] | moderate |
| Words flagged "not recognised", by expert word rating | perfect 23.6%; accented-but-correct 50.0% (26/52); mispronounced 82.2% | **penalises accent** |
| False corrections (flagged words experts rated acceptable) | 77.3% [74.2%, 80.2%] (566/732) | word-level corrections would mostly be wrong |
| Pronunciation proxy vs expert word accuracy | dev 0.371 [0.338, 0.404]; test 0.322 [0.292, 0.348]; gate 0.35 | **fails on held-out test** |
| Latency (CPU) | p50 5.2 s, p90 6.5 s for 3.5 s median audio (real-time factor about 1.5); cost $0; failures 0/700 | |

### Synthetic Spanish (Edge TTS; native voices, no expert labels)

| Measure | Result |
|---|---|
| WER by accent (clean) | Spain 0.030, Mexico 0.038, Colombia 0.101, Argentina 0.111 |
| WER by rate | +0%: 0.058, +25%: 0.058 |
| WER by SNR | clean 0.017, 20 dB 0.021, 10 dB 0.056, 0 dB 0.361 |
| Correct words flagged "not recognised" | Spain 2.4%, Mexico 3.1%, Colombia 9.0%, Argentina 9.7% |
| Learner grammar errors kept by the recogniser | 86.1% (124/144); silently "corrected" 0.7%; other changes 13.2% |
| Silence / noise-only clips with graded evidence | 0 / 4 and 0 / 4 |
| Noisy speech flagged `noisy` | 0 dB: 100%; 10 dB and 20 dB: 0% |

### Formats (offline English TTS, synthetic)

All six formats (wav, flac, mp3, ogg, webm, mp4) decoded 4/4 with WER 0.
Silence and clipping are flagged; too-short, too-long, mislabelled and
non-audio input are rejected with their codes. A truncated webm decoded
without a quality flag.

### Decisions taken from these results

| Decision | Evidence |
|---|---|
| **Fluency is scored for English read-aloud only** (`FLUENCY_VALIDATED`); everywhere else it is measures-only exposure | the map beats both baselines on held-out experts, but it was fitted and tested only on English read-aloud |
| **Pronunciation proxy stays off** (`PRONUNCIATION_VALIDATED` empty) | dev passed narrowly, held-out test failed (CI entirely below 0.35). The gate now requires both. |
| **No word-level "not recognised" corrections**; one neutral note instead | 77% false corrections; accented-but-correct words flagged half the time; Rioplatense/Colombian voices about 4x Castilian |
| **Intelligibility confidence 0.5 (English) / 0.3 (other)**, not scaled by transcript confidence | moderate expert agreement; transcription confidence is applied separately by the learner model |
| **Repetition-loop gate** | 5/700 loops with high confidence |
| **Spoken grammar stays limited to confident free speech** | the recogniser keeps 86% of learner errors on clean synthetic speech; that is only an upper bound, since real learners and noise are not covered |

### What these results do not show

- Nothing about Spanish (or any language other than English) against
  experts: none of these scores is validated for Spanish.
- Nothing about free speech, other L1s, or real classroom microphones.
- The listening bank is author-labelled; listening scores have no expert
  validation.
- The synthetic accent results come from one voice or two per region; they
  show a recogniser bias, but its size for real speakers is unknown.
