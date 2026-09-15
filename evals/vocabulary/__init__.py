"""Vocabulary evaluation suite.

Scope note: the vocabulary agent (:mod:`src.agents.vocabulary`) only
*extracts* candidate words from a raw JSON-ish model response
(:func:`_parse_vocabulary_response`); unlike grammar, it has no
classification/confidence/abstention layer to test (see
``POLYGLOT_SWARM_10_10_IMPLEMENTATION_PLAN.md`` Phase 18, "Vocabulary" metrics).
So this suite measures what is actually measurable offline today:

- **extraction precision/recall/F1** — given a raw model response, does the
  parser recover the expected word set and reject malformed/empty payloads
  without crashing?

"Sense accuracy" and "contextual appropriateness" need a live model or a human
rater to judge meaning-in-context and are explicitly out of scope for this
offline suite; "mastery prediction" is covered by the assessment suite instead
(mastery -> CEFR band), since that is where the mastery model actually lives.
"""
