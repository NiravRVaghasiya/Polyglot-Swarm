# Labeling rubric

Versions: `grammar-rubric-1.0`, `vocabulary-rubric-1.0` (2026-11-06).
A dataset records which rubric version its labels follow. Any change to the
rules below needs a new rubric version and a new dataset version.

## Grammar cases

**The question.** Each case asks one thing: *should a language tutor flag an
error in this learner text?*

- `has_error: true` — a careful native speaker would not produce the text in
  the stated situation, and correcting it would help the learner.
- `has_error: false` — the text is acceptable, including regional, informal
  or formal variants and synonyms. Flagging it is a **false correction**.
- `has_error: null` (category `ambiguous`) — competent annotators could
  reasonably disagree, because the text is normatively disputed or its
  correctness depends on unstated context. Not flagging is the preferred
  behaviour; neither answer is scored as wrong.

### Categories

| Category | Use when | Label |
|---|---|---|
| `correct` | plain, unmarked correct text | false |
| `incorrect` | a grammatical error (agreement, tense, mood, case, word order, prepositions, ...) | true |
| `vocabulary_misuse` | a wrong word: false friend, wrong collocation; the expected error has `skill: vocabulary` | true |
| `context_inappropriate` | grammatical, but the register is wrong for the stated `context`; the expected error has `skill: pragmatics` | true |
| `acceptable_alternative` | an alternative correct form or a synonym (tag `synonym`) | false |
| `regional` | valid in a region or dialect (tag the dialect) | false |
| `formal` / `informal` | valid, marked register, with no context making it inappropriate | false |
| `ambiguous` | see above | null |
| `adversarial` | prompt injection or a misleading claim embedded in the text; label the actual language | true/false |

### Expected errors

For every error, record:

- `span` — an exact substring of the text;
- `corrections` — every accepted correction;
- `constructions` — accepted construction ids, normalized lowercase with
  underscores, canonical one first;
- `skill`;
- the construction's own CEFR level, when known.

### Other fields

- `cefr_level` is the proficiency of the (simulated) learner who wrote the
  text.
- `difficulty` is how hard the case is to judge: `easy` for a textbook
  error; `medium` when it needs knowledge of one rule; `hard` when it needs
  context, register awareness, or knowledge of a disputed norm.

## Vocabulary cases

**The question.** Each case asks *which words in this exchange should the
vocabulary agent extract for a learner at this level?* The prompt's rules
apply: skip basic words, proper nouns and numbers.

- `required` words are ones a learner at the stated level is very unlikely to
  know. Record the accepted surface forms (`forms`), the accepted English
  glosses, and whether the word occurs in the learner's own text
  (`produced`).
- `optional` words are reasonable to extract but not required. Extracting
  them never counts against precision.
- `forbidden` words break the prompt's rules.

## Provenance

Each case gets one annotation per annotator. That annotation records:

- annotator id and type (`expert`, `trained_annotator`, `author`, or
  `llm_assistant`);
- the label;
- the rubric version;
- the date.

`validation_status` is `expert_validated` only when at least one annotation is
from an `expert` or `trained_annotator`. It is `author_labeled` otherwise, and
`synthetic` for generated cases. If annotators disagree, keep every annotation
and record the adjudicated label at case level.
