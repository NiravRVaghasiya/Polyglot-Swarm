# 0034. Multimodal (speech) assessment

- Status: Accepted
- Date: 2026-11-07
- Amends: [0031](0031-evidence-driven-learner-knowledge-model.md) (evidence model), [0033](0033-adaptive-learning-intelligence.md) (planner activities)

## Context

Voice existed only as dictation. The browser recorded webm, and
`/api/v1/voice/transcribe` returned Whisper's text for the chat. Nothing
assessed speaking or listening. The gaps:

- **Transcription:** no word timing, confidence or language identification
  was kept.
- **Pronunciation:** `src/speech/pronunciation.py` compared a transcript with
  a target sentence and called the result "pronunciation". That is a claim of
  phonetic accuracy from text alone.
- **Listening:** there were no comprehension tasks, although the planner
  proposed `listening_check` activities.
- **Evidence model:** it had no modality, no media reference and no place
  for recogniser uncertainty.
- **VAD:** it used `audioop`, which Python 3.13 removes.
- **Data:** the project had no learner audio and no expert-labelled speech.

## Decision

1. **Separate stages with typed hand-offs** (`src/multimodal/contracts.py`):
   capture/ingest → process → assess → evidence → LKM. The contracts are
   modality-neutral (`Modality`, `MediaAsset`, `Observation`,
   `DimensionResult`, `AssessmentReport`). A later image, video or real-time
   ingestor plugs in without touching the assessment core.
2. **Ingestion** (`audio.py`):
   - sniffing magic bytes, and rejecting a declared format that disagrees;
   - size and duration limits;
   - decoding to 16 kHz mono with ffmpeg, under a timeout;
   - a signal-quality report covering silence, noise (SNR), clipping and
     voiced regions.

   Quality problems are flagged, not rejected; invalid input gets a stable
   error code.
3. **Speech-to-text behind a provider protocol** (`transcription.py`).
   - `WhisperLocalProvider` keeps segments, word timestamps, word
     probabilities, the detected language and its probability.
   - Retries cover transient errors; `unavailable` and
     `unsupported_language` are not retried and never fall back silently to
     another provider.
   - Silence is never sent to the recogniser, and Whisper's own no-speech rule
     drops hallucinated segments.
4. **Speaking dimensions with an explicit basis, and abstention**
   (`speaking.py`):
   - `fluency` — **timing** measures only: rate, pauses, run length,
     repetitions, fillers. It is mapped to a score by a logistic map fitted on
     expert ratings. Confidence is lower outside the validated language.
   - `intelligibility` — **transcript**: the share of target words the
     recogniser understood. This is explicitly *not* pronunciation, and it
     normalises away accent marks.
   - `pronunciation` — an **acoustic proxy** (word probability). It is
     assessed only for languages where it passed a validation gate against
     expert word ratings, and abstains otherwise.
   - `spoken_grammar` — the existing grammar agent run on the transcript. It
     runs only for free speech with a confident transcript, and is marked as
     transcript-derived.
5. **Listening** (`listening.py`).
   - Learners answer by choosing or typing, so the score is independent of
     speech recognition and of speaking ability.
   - Questions are typed as `recognition`, `comprehension` or `recall`.
   - Tasks vary in voice/accent, rate and CEFR level.
   - The task bank is author-written and labelled as such.
6. **Evidence** (schema v3, migration 0009). New fields:
   - `modality`;
   - `media_ref`;
   - `processing`;
   - `transcription_confidence`, kept separate from `confidence`.

   The v2 engine multiplies the two for transcript-derived evidence, so a
   poor recording counts for less and is never read as poor ability. It also
   accepts a `scored` outcome in [0, 1].

   All events from one recording share a correlation key derived from the
   audio hash, so a resubmission merges instead of double-counting. Measures
   without a validated score are recorded as exposure. Evidence never holds
   transcript text.
7. **Privacy** (`store.py`).
   - Raw audio is not kept unless the learner consents (`retain_audio`). It
     is then kept for at most 30 days and purged automatically.
   - Derived artifacts are in `media_submissions`, which privacy export and
     deletion cover.
   - Every read is user-scoped.
   - Logs contain ids, sizes and statuses, never audio or transcripts.
8. **API and frontend.**
   - New endpoints: `/api/v1/assessment/speaking`, the listening task,
     audio and answers endpoints, and submissions (list, get, delete).
   - The React app gains a listening exercise and `useVoice.stopAndAssess`.
   - The planner maps `speaking` → `speaking_check` and
     `pronunciation` → `read_aloud`.
9. **Evaluation** (`evals/speech`), on three kinds of data, never mixed:
   - **External, expert-labelled:** speechocean762, English read-aloud by
     Mandarin-L1 learners.
   - **Synthetic Spanish:** Edge TTS in six regional voices, at two speech
     rates and three noise levels.
   - **Synthetic offline English:** for formats and edge cases.

   All three use the real recogniser.

## Consequences

- Speaking and listening now produce separate, typed evidence, with
  provenance, modality and both kinds of uncertainty.
- The validity of every number is bounded by the data used to check it.
  - The only expert comparison is English read-aloud by Mandarin-L1
    speakers.
  - Fluency is scored only for English read-aloud, the validated scope
    (Spearman 0.60 vs 0.13 for a text-only baseline; 0.42 for children).
    For Spanish it is measures-only exposure, and pronunciation abstains:
    the proxy failed the held-out gate.
  - Real learner studies and Spanish expert labels are the next requirements.
- The benchmark showed the recogniser is not accent-neutral: 77% of
  "not recognised" words were acceptable to experts, and correct Rioplatense
  and Colombian synthetic speech was missed about 4x as often as Castilian.
  Intelligibility therefore gives no word-level corrections, and its
  confidence is low.
- Whisper can loop on a phrase with high word probabilities, so a
  compression-ratio gate abstains on such transcripts.
- A dimension's `confidence` is the judgment's reliability only; the
  recogniser's confidence is applied once, by the learner model.
- `src/speech/pronunciation.py` is left in place for backward compatibility,
  but the new pipeline does not use it, and its "pronunciation" wording
  should not be surfaced to learners.
- Whisper base on CPU takes several seconds per utterance (see the benchmark
  for real-time factors), so speaking assessment is asynchronous in spirit
  even though the endpoint waits for it.
