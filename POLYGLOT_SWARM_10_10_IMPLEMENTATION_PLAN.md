# Polyglot Swarm — 10/10 Implementation Plan

## Executive goal

Turn Polyglot Swarm from a promising multi-agent language-learning prototype into a **validated, production-grade adaptive language-learning system**.

The goal is not to maximize the number of agents.

The goal is to build a system that can credibly demonstrate:

> **The system maintains an accurate model of a learner's language competence and uses that model to select the next best learning interaction, producing measurable gains in retention, accuracy, fluency, and transfer.**

The existing repository already has a useful foundation: LangGraph orchestration, Conversation/Grammar/Vocabulary agents, FSRS integration, a proposed SQLite + ChromaDB memory layer, scenario support, multi-provider LLM intent, assessment/transfer concepts, and a roadmap through voice and a React frontend. The current implementation plan also correctly identifies persistence and provider abstraction as foundational gaps. The 10/10 plan below keeps those foundations but changes the priority order around **learner modeling, evaluation, correctness, observability, and evidence**.

---

# 1. Definition of 10/10

A 10/10 Polyglot Swarm should satisfy all of these:

### Learning

- Learner state persists across sessions and devices.
- The system models **skill-specific competence**, not merely "known words."
- Vocabulary, grammar, pronunciation, comprehension, fluency, pragmatics, and transfer are represented separately.
- Review scheduling is driven by demonstrated performance.
- New interactions deliberately target the learner's highest-value weaknesses.
- The system measures delayed retention, not just immediate correctness.
- Difficulty adapts continuously but remains pedagogically controlled.

### AI quality

- Corrections have calibrated confidence.
- False corrections are aggressively suppressed.
- Multiple valid/native variants are recognized.
- Grammar, vocabulary, cultural and pragmatic judgments are reconciled.
- The system can abstain when uncertain.
- Model/provider failures degrade gracefully.
- LLM output is structured and schema validated.
- Every important model decision is observable and reproducible.

### Language quality

- Language-specific linguistic resources exist where generic prompting is insufficient.
- Dialect, register, morphology, syntax and pragmatic differences are explicit.
- Cross-language transfer includes both positive transfer and negative transfer.
- False friends are first-class learning objects.
- CEFR is treated as a multidimensional profile rather than a single number.

### Engineering

- Every critical component is tested.
- LLM calls are mockable and benchmarkable.
- Evaluation datasets are version controlled.
- CI blocks regressions.
- Database migrations are safe.
- Authentication, authorization, rate limiting and secret management are production-grade.
- Costs, latency and token usage are tracked.
- Local/self-hosted mode remains viable.

### Evidence

The project publishes:

- component-level benchmarks,
- end-to-end tutor benchmarks,
- calibration results,
- retention experiments,
- ablation studies,
- cost/latency measurements,
- limitations and known failure cases.

---

# 2. The architectural north star

Move from:

```text
User
  |
  v
Conversation Agent
  |
  +--> Grammar Agent
  +--> Vocabulary Agent
  +--> Culture Agent
  +--> Transfer Agent
  +--> Evaluator
  |
  v
FSRS
```

toward:

```text
                         USER
                           |
                           v
                 +-------------------+
                 | Interaction Layer |
                 | text / voice /    |
                 | writing / reading  |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | Conversation       |
                 | Engine             |
                 +---------+---------+
                           |
                           v
                 +-------------------+
                 | Event / Evidence   |
                 | Stream             |
                 +---------+---------+
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
   Grammar Analysis   Lexical Analysis   Pragmatics
          |                |                |
          +----------------+----------------+
                           |
                           v
                 +-------------------+
                 | Learner Knowledge |
                 | Model             |
                 +---------+---------+
                           |
       +-------------------+-------------------+
       |                   |                   |
       v                   v                   v
  Assessment         Curriculum          Memory/SRS
       |                   |                   |
       +-------------------+-------------------+
                           |
                           v
                 +-------------------+
                 | Next Best         |
                 | Learning Action   |
                 +---------+---------+
                           |
                           v
                       USER

Independent QA / verifier:
-----------------------------------------
Runs across critical AI decisions.
Can accept / reject / modify / abstain.
```

## Critical architectural principle

Do **not** turn every subsystem into an LLM agent.

Use LLMs for reasoning.

Use deterministic services for:

- FSRS scheduling
- database operations
- aggregation
- scoring
- authentication
- authorization
- telemetry
- feature flags
- migrations
- validation
- policy enforcement

This reduces cost, latency, nondeterminism and debugging complexity.

---

# 3. The real product: Learner Knowledge Model

The strongest potential differentiator is not "seven agents."

It is the **persistent computational model of the learner**.

Create:

```text
src/learner/
    models.py
    knowledge_state.py
    evidence.py
    update.py
    mastery.py
    uncertainty.py
    calibration.py
```

## 3.1 Skill model

Represent at minimum:

```text
language
  ├── vocabulary
  │    ├── recognition
  │    ├── production
  │    ├── listening
  │    └── spelling
  ├── grammar
  │    ├── construction-level mastery
  │    └── error patterns
  ├── pronunciation
  ├── listening
  ├── reading
  ├── writing
  ├── speaking
  ├── interaction
  └── pragmatics
```

Do not collapse these into one proficiency value.

Example:

```json
{
  "language": "pl",
  "skills": {
    "speaking": 0.54,
    "listening": 0.68,
    "reading": 0.73,
    "writing": 0.49,
    "grammar": 0.52,
    "vocabulary": 0.65,
    "pragmatics": 0.41
  },
  "uncertainty": {
    "speaking": 0.12,
    "grammar": 0.09
  }
}
```

## 3.2 Evidence-based updates

Never update mastery merely because an LLM says "correct."

Every learner-state update should reference evidence:

```text
Evidence
  ├── interaction_id
  ├── item_id
  ├── skill
  ├── observed_response
  ├── expected_response
  ├── assessment
  ├── confidence
  ├── model_version
  └── timestamp
```

This gives you:

- explainability,
- debugging,
- reproducibility,
- rollback,
- longitudinal analysis.

---

# 4. Phase 0 — Repository stabilization

## Goal

Make the current project trustworthy before adding more features.

### Tasks

- [ ] Fix README clone URL.
- [ ] Make the documented commands actually executable.
- [ ] Add a single canonical `make`/`just`/`task` workflow.
- [ ] Add CI.
- [ ] Add formatting/linting/type checking.
- [ ] Add pre-commit hooks.
- [ ] Add dependency lockfile.
- [ ] Add semantic versioning.
- [ ] Add changelog.
- [ ] Add architecture decision records.
- [ ] Add contribution and development setup documentation.
- [ ] Add `.env.example` validation.
- [ ] Add health check.
- [ ] Add deterministic test mode.

### Acceptance criteria

```text
make test
make lint
make typecheck
make benchmark
```

all work from a clean checkout.

---

# 5. Phase 1 — Provider abstraction

The existing plan correctly prioritizes this.

## Implementation

Create:

```text
src/llm/
    provider.py
    router.py
    claude.py
    gemini.py
    openai.py
    ollama.py
    schemas.py
    telemetry.py
```

## Requirements

Every provider supports:

```text
generate()
generate_structured()
stream()
count_tokens()
health()
```

Use structured output wherever possible.

## Provider routing

Define task tiers:

```text
critical_reasoning
fast_extraction
cheap_classification
local_private
```

Do not simply map one agent to one provider.

Route by task.

Example:

```text
Conversation:
    primary reasoning model

Grammar extraction:
    fast structured model

FSRS:
    no LLM

Difficulty scoring:
    deterministic + optional verifier

High-risk correction:
    strong model + verifier
```

## Acceptance criteria

- [ ] Providers interchangeable.
- [ ] Provider failure triggers controlled fallback.
- [ ] Provider latency/cost recorded.
- [ ] Structured responses schema validated.
- [ ] No agent imports a vendor SDK directly.

---

# 6. Phase 2 — Persistent memory

Use the existing SQLite + ChromaDB direction, but establish clear ownership.

## SQLite owns

- users
- profiles
- sessions
- turns
- vocabulary
- grammar patterns
- learner-state snapshots
- evidence
- assessments
- FSRS cards
- analytics
- experiments

## Vector store owns

- semantic conversation memories
- contextual examples
- cultural notes
- retrieved learning content

Never use vector search as the source of truth for learner state.

## Required schema

At minimum:

```text
users
profiles
languages
sessions
turns
learning_events
vocabulary_items
grammar_items
grammar_errors
skill_states
evidence
fsrs_cards
assessments
scenarios
scenario_attempts
experiments
model_runs
```

## Acceptance criteria

A user can:

1. start a session,
2. learn something,
3. close the application,
4. restart it,
5. authenticate,
6. resume,
7. receive a review generated from previous evidence.

---

# 7. Phase 3 — Evidence pipeline

This is the most important new subsystem.

Create:

```text
src/evidence/
    events.py
    extractor.py
    normalizer.py
    deduplicator.py
    confidence.py
    provenance.py
```

Every interaction emits structured events:

```text
TURN_COMPLETED
VOCAB_OBSERVED
VOCAB_PRODUCED
GRAMMAR_ERROR
GRAMMAR_SUCCESS
PRAGMATIC_EVENT
PRONUNCIATION_EVENT
COMPREHENSION_RESULT
REVIEW_RESULT
SCENARIO_OBJECTIVE_COMPLETED
```

Example:

```json
{
  "event_type": "GRAMMAR_ERROR",
  "language": "es",
  "construction": "ser_vs_estar",
  "confidence": 0.94,
  "source": "grammar-v3",
  "interaction_id": "..."
}
```

The learner model consumes events.

This separates:

```text
what happened
```

from:

```text
what we currently believe about the learner
```

That distinction is fundamental.

---

# 8. Phase 4 — Grammar intelligence

Replace free-form grammar feedback with a structured taxonomy.

## Grammar item

```text
grammar_item
  ├── language
  ├── construction
  ├── CEFR
  ├── explanation
  ├── examples
  ├── prerequisites
  └── common_interferences
```

## Grammar event

```text
error
  ├── construction
  ├── severity
  ├── confidence
  ├── correction
  ├── alternatives
  ├── explanation
  └── evidence
```

## Critical behavior

The system must distinguish:

```text
wrong
awkward
unusual
regional
formal
informal
acceptable alternative
```

Never treat all deviations as errors.

## Acceptance targets

Establish a benchmark with:

- native-acceptable sentences,
- genuinely incorrect sentences,
- dialectal variants,
- informal language,
- idioms,
- ambiguous cases.

Target:

```text
high precision > raw recall
low false-correction rate
calibrated confidence
```

The exact numerical threshold should be established empirically rather than invented in advance.

---

# 9. Phase 5 — Vocabulary intelligence

Stop modeling vocabulary as simply:

```text
known / unknown
```

Use dimensions:

```text
recognition
production
listening
spelling
contextual appropriateness
```

Example:

```json
{
  "lemma": "mesa",
  "recognition": 0.92,
  "production": 0.61,
  "listening": 0.79,
  "spelling": 0.88
}
```

Track:

- first seen,
- first produced,
- successful productions,
- failed productions,
- contexts,
- collocations,
- register,
- frequency,
- CEFR,
- FSRS state.

## Add collocations

Language competence is not just word knowledge.

Model:

```text
tomar una decisión
hacer una pregunta
tener ganas de
```

as learning objects.

This is a major quality upgrade.

---

# 10. Phase 6 — Learner model and mastery engine

Create:

```text
src/learner/
    knowledge_model.py
    mastery_engine.py
    uncertainty.py
    skill_graph.py
```

Use evidence to update beliefs.

For every item:

```text
prior belief
      +
new evidence
      ↓
posterior belief
      +
uncertainty
```

Do not require a complex Bayesian model on day one.

A robust weighted evidence model is sufficient for MVP.

Later evaluate:

- Bayesian Knowledge Tracing,
- Item Response Theory,
- Deep Knowledge Tracing,
- logistic mastery models.

The important part is the **interface**, not premature algorithmic complexity.

---

# 11. Phase 7 — Next Best Learning Action

This is the strategic heart of the product.

Create:

```text
src/curriculum/
    planner.py
    actions.py
    constraints.py
    difficulty.py
    objectives.py
```

Possible actions:

```text
continue_conversation
review_vocab
target_grammar
contrast_two_forms
pronunciation_drill
listening_check
writing_exercise
reading
retrieval_practice
scenario
transfer_exercise
```

The planner selects:

```text
argmax Expected Learning Value
```

subject to:

```text
learner goal
time available
fatigue
difficulty
due reviews
scenario context
skill balance
```

Example:

```text
User goal: conversational Polish

Highest priority:
1. case production weakness
2. due vocabulary
3. pronunciation of selected phonemes

Next action:
restaurant scenario requiring instrumental case
```

This is much more powerful than "start another random conversation."

---

# 12. Phase 8 — FSRS integration

Keep FSRS deterministic.

Do not make it an autonomous LLM agent.

Use FSRS to schedule item review, while the curriculum engine decides **what should be learned/reviewed**.

The distinction:

```text
Curriculum engine:
    What should the learner practice?

FSRS:
    When should this item be reviewed?
```

Add contextual review generation:

```text
due item
   ↓
current learner context
   ↓
scenario-compatible prompt
   ↓
retrieval attempt
   ↓
assessment
   ↓
FSRS update
```

Measure actual recall rather than assuming scheduler quality equals learning quality.

---

# 13. Phase 9 — Evaluator / verifier

The Evaluator should become a genuine safety and quality layer.

Create:

```text
src/evaluation/
    verifier.py
    conflict.py
    calibration.py
    policies.py
```

For every high-impact correction:

```text
candidate correction
       ↓
linguistic verification
       ↓
confidence calibration
       ↓
accept / revise / abstain
```

Possible output:

```json
{
  "decision": "abstain",
  "confidence": 0.48,
  "reason": "Multiple regional variants are acceptable"
}
```

**Abstention is a feature.**

A tutor that says "I'm not confident this is wrong" is better than one that confidently teaches incorrect language.

---

# 14. Phase 10 — Language packs

Replace the "any language with no configuration" claim with a more defensible architecture.

Create:

```text
languages/
    es/
    pl/
    it/
    ja/
    ...
```

Each pack can contain:

```text
metadata.yaml
grammar/
frequency/
collocations/
register/
pronunciation/
transfer/
scenarios/
assessment/
```

Generic agent infrastructure stays reusable.

Language-specific knowledge becomes explicit.

## Initial validation languages

Use three intentionally different languages:

### Spanish

Baseline Romance language.

### Polish

High morphology / case / aspect complexity.

### Japanese

Different writing system, particles, honorifics and syntax.

If one architecture works credibly across these three, the "multilingual" claim becomes much stronger.

---

# 15. Phase 11 — Cross-language transfer

Build a proper transfer graph:

```text
Language A
   |
   +--> cognate
   +--> false friend
   +--> shared construction
   +--> interference risk
   +--> pronunciation transfer
   +--> syntax transfer
```

Example:

```text
Spanish → Italian

positive:
familia → famiglia

negative:
false friend
syntax interference
pronunciation interference
```

Do not rely only on embedding similarity.

Use:

```text
candidate retrieval
+
linguistic resource
+
LLM verification
```

---

# 16. Phase 12 — Assessment / CEFR

Do not output only:

```text
B1
```

Output a profile:

```text
Spanish

Speaking       B1-
Listening      B1+
Reading        B2-
Writing        A2+
Grammar        B1-
Vocabulary     B1
Pragmatics     A2+
```

Track confidence and sample size:

```text
Speaking: B1- ± 0.3
Evidence: 184 observations
Confidence: medium
```

## Validate assessment

Compare against:

- expert ratings,
- established language tests,
- blinded human evaluation.

Publish correlation/error statistics.

Never present CEFR estimation as validated until this exists.

---

# 17. Phase 13 — Scenario engine

Scenarios should become pedagogical environments, not merely prompts.

Each scenario needs:

```yaml
id:
language:
level:
persona:
context:
objectives:
target_grammar:
target_vocabulary:
target_functions:
constraints:
success_criteria:
failure_conditions:
transfer_opportunities:
```

Example:

```text
Restaurant

Objectives:
- order food
- ask for clarification
- express preference
- handle a misunderstanding

Target grammar:
- polite requests
- quantity expressions

Target vocabulary:
- menu
- ordering
- dietary restrictions
```

The system should deliberately create opportunities for target skills.

---

# 18. Phase 14 — Adaptive difficulty

Difficulty should respond to multiple signals:

```text
accuracy
response latency
repair frequency
lexical diversity
grammar complexity
comprehension
confidence
frustration/fatigue signals
```

Avoid simply:

```text
more correct → harder
```

Instead use a difficulty controller.

```text
too easy
    ↓
increase complexity

optimal challenge
    ↓
maintain

too difficult
    ↓
scaffold
```

---

# 19. Phase 15 — Voice

Voice should be built after the text learning loop is validated.

Pipeline:

```text
microphone
   ↓
VAD
   ↓
STT
   ↓
language detection
   ↓
conversation
   ↓
learning evidence
   ↓
TTS
```

Add pronunciation evaluation separately.

Do not infer pronunciation quality solely from transcript text.

Where possible, collect:

- phoneme alignment,
- pronunciation confidence,
- prosody,
- stress,
- fluency,
- repair behavior.

---

# 20. Phase 16 — Production frontend

React/Next.js should expose the learner model, not just chat.

Core screens:

```text
Home
 ├── today's plan
 ├── due reviews
 ├── current goal
 └── weak areas

Conversation
 ├── scenario
 ├── conversation
 └── subtle coaching

Review
 ├── retrieval practice
 └── contextual examples

Progress
 ├── skill map
 ├── vocabulary
 ├── grammar
 ├── retention
 └── CEFR profile

Insights
 ├── recurring errors
 ├── transfer opportunities
 └── recommendations
```

The UI should answer:

> "What should I practice today, and why?"

---

# 21. Phase 17 — Observability

Add OpenTelemetry-compatible tracing.

Track:

```text
request_id
user_id
session_id
interaction_id
model
provider
prompt_version
latency
tokens
cost
tool calls
agent decisions
evaluation result
```

Build an internal trace viewer.

For any bad tutor response, you should be able to reconstruct:

```text
user input
→ retrieved memory
→ prompt
→ model output
→ grammar analysis
→ evaluator decision
→ learner-state update
→ curriculum decision
```

Without this, production debugging will be painful.

---

# 22. Phase 18 — Evaluation harness

Create:

```text
evals/
    grammar/
    vocabulary/
    pragmatics/
    assessment/
    transfer/
    conversation/
    curriculum/
    safety/
    regression/
```

Every model/prompt change runs evaluation.

## Metrics

### Grammar

- precision
- recall
- F1
- false correction rate
- calibration error

### Vocabulary

- extraction precision
- sense accuracy
- contextual appropriateness
- mastery prediction

### Assessment

- correlation with expert ratings
- absolute error
- calibration
- confidence coverage

### Curriculum

- target coverage
- skill balance
- difficulty appropriateness
- learner success rate

### Product

- latency
- cost/session
- failure rate
- retention
- engagement

---

# 23. Phase 19 — Learning science experiment platform

This is what can take the project from "excellent engineering" to "serious educational technology."

Create experiment support:

```text
experiments
experiment_variants
assignments
outcomes
```

Support controlled comparisons.

Minimum experiment:

```text
Control:
generic LLM conversation

Treatment:
Polyglot Swarm adaptive tutor
```

Measure:

```text
pre-test
intervention
immediate post-test
1-day delayed test
7-day delayed test
30-day delayed test
```

## More useful ablations

Compare:

```text
A: conversation only

B: conversation + memory

C: conversation + FSRS

D: conversation + learner model

E: full Polyglot Swarm
```

This tells you **which architectural components actually create value**.

---

# 24. Phase 20 — Safety and correctness

Implement policies for:

- hallucinated corrections
- fabricated cultural claims
- sensitive content
- inappropriate personas
- medical/legal role-play
- prompt injection through external content
- malicious scenario definitions
- unsafe user-generated content
- privacy and deletion

External text must always be treated as untrusted data.

Never allow retrieved content to become system instructions.

---

# 25. Phase 21 — Security and privacy

For a self-hostable product, make privacy a feature.

Implement:

- password hashing,
- secure sessions/tokens,
- authorization checks,
- rate limiting,
- encrypted secrets,
- database backups,
- user data export,
- user data deletion,
- audit logs,
- configurable telemetry,
- local-only mode.

The user should be able to run:

```text
UI
+
API
+
SQLite
+
Chroma
+
local LLM
+
local STT
+
local TTS
```

without sending learning data to third parties.

---

# 26. Phase 22 — Cost and latency optimization

Track cost per:

```text
conversation turn
session
learning event
review
assessment
```

Create a budget-aware router.

Example:

```text
cheap model:
    extraction

medium model:
    normal conversation

strong model:
    difficult correction / evaluator

local model:
    privacy mode
```

Cache deterministic/static information.

Do not send the entire learner history to the LLM.

Retrieve only relevant evidence.

---

# 27. Phase 23 — Production reliability

Implement:

- retries with bounded backoff,
- circuit breakers,
- idempotent writes,
- transaction boundaries,
- database migrations,
- background jobs,
- queueing,
- graceful degradation,
- health/readiness probes,
- backup/restore,
- structured logs.

Failure examples:

```text
LLM unavailable
→ local fallback

Vector store unavailable
→ continue with structured state

Evaluator unavailable
→ suppress uncertain correction

TTS unavailable
→ text mode

Analytics unavailable
→ do not block conversation
```

The conversation path should remain resilient.

---

# 28. Phase 24 — Open-source quality

Make the repository itself 10/10.

Add:

```text
docs/
    architecture.md
    learner-model.md
    evaluation.md
    language-packs.md
    providers.md
    privacy.md
    deployment.md
    contributing.md
    ADR/
```

Add:

- issue templates,
- pull-request template,
- security policy,
- code of conduct,
- release process,
- benchmark reports,
- demo videos,
- reproducible evaluation instructions.

---

# 29. Recommended implementation order

Do **not** follow a feature-first roadmap.

Use this order:

```text
1. Stabilize repository
2. Provider abstraction
3. Persistence
4. Evidence pipeline
5. Learner Knowledge Model
6. Grammar correctness
7. Vocabulary mastery
8. FSRS
9. Evaluator/verifier
10. Next Best Learning Action
11. Language packs
12. Scenarios
13. Assessment
14. Transfer
15. Evaluation harness
16. Learning experiments
17. Analytics UI
18. Voice
19. Production auth/security
20. Scale/deployment
```

Voice and frontend polish come after the learning engine is validated.

---

# 30. Definition of Done for 10/10

The project should not be called 10/10 merely because all modules exist.

It should pass these gates.

## Gate A — Functional

- [ ] Persistent multi-user sessions.
- [ ] Text conversation.
- [ ] Vocabulary extraction.
- [ ] Grammar analysis.
- [ ] Cultural/pragmatic analysis.
- [ ] FSRS reviews.
- [ ] Learner model.
- [ ] Adaptive curriculum.
- [ ] Assessment.
- [ ] Transfer.
- [ ] Scenarios.
- [ ] Voice.
- [ ] Dashboard.

## Gate B — Correctness

- [ ] Structured LLM outputs.
- [ ] Evaluator/verifier.
- [ ] Abstention.
- [ ] Versioned prompts.
- [ ] Regression suite.
- [ ] Language-specific tests.
- [ ] Low false-correction rate.

## Gate C — Learning

- [ ] Delayed-retention measurement.
- [ ] Pre/post assessment.
- [ ] Controlled comparison.
- [ ] Ablation study.
- [ ] Published results.
- [ ] Known limitations.

## Gate D — Production

- [ ] Authentication.
- [ ] Authorization.
- [ ] Rate limiting.
- [ ] Observability.
- [ ] Backups.
- [ ] Migrations.
- [ ] Cost tracking.
- [ ] Graceful degradation.
- [ ] Privacy controls.

## Gate E — Product

- [ ] Daily learning plan.
- [ ] Clear learner goals.
- [ ] Explainable recommendations.
- [ ] Progress visualization.
- [ ] Contextual review.
- [ ] Low-friction onboarding.
- [ ] Voice interaction.
- [ ] Excellent mobile experience.

---

# 31. Suggested target KPIs

Do not hard-code arbitrary claims such as "92% retention" into the product narrative.

Instead establish measurable targets through benchmarks.

Track:

| KPI | Target direction |
|---|---|
| Grammar false-positive rate | ↓ |
| Grammar precision | ↑ |
| Assessment error | ↓ |
| Calibration error | ↓ |
| Delayed vocabulary retention | ↑ |
| Grammar transfer | ↑ |
| Session completion | ↑ |
| Learner return rate | ↑ |
| Cost/session | ↓ |
| Median response latency | ↓ |
| Recovery from provider failure | ↑ |
| User-reported correction trust | ↑ |

The most important KPI is:

> **Delayed learning gain per minute of learner time.**

That forces the product to optimize learning rather than chatbot engagement.

---

# 32. The five breakthroughs that matter most

If engineering capacity is limited, prioritize these five.

## 1. Learner Knowledge Model

Make the system know what the learner actually knows.

## 2. Evidence + provenance

Make every learner-state change explainable.

## 3. Next Best Learning Action

Make every interaction intentional.

## 4. Verifier + abstention

Make the tutor trustworthy.

## 5. Controlled learning evaluation

Prove the system works.

These five are more important than adding another agent.

---

# 33. Final architecture

The final system should conceptually look like:

```text
                         ┌───────────────┐
                         │     USER      │
                         └───────┬───────┘
                                 │
                    text / voice / writing
                                 │
                                 v
                    ┌─────────────────────┐
                    │ Interaction Engine  │
                    └──────────┬──────────┘
                               │
                               v
                    ┌─────────────────────┐
                    │ Evidence Pipeline   │
                    └──────────┬──────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             v                 v                 v
         Grammar           Vocabulary        Pragmatics
         Analysis           Analysis         Analysis
             │                 │                 │
             └─────────────────┼─────────────────┘
                               │
                               v
                  ┌────────────────────────┐
                  │ Learner Knowledge Model│
                  └───────────┬────────────┘
                              │
          ┌───────────────────┼────────────────────┐
          │                   │                    │
          v                   v                    v
     Assessment          Curriculum             FSRS
          │              /Planner             Scheduler
          │                   │                    │
          └───────────────────┼────────────────────┘
                              │
                              v
                 ┌────────────────────────┐
                 │ Next Best Learning     │
                 │ Action                 │
                 └───────────┬────────────┘
                             │
                             v
                           USER


     ┌──────────────────────────────────────────────┐
     │ Independent QA / Verifier / Calibration     │
     └──────────────────────────────────────────────┘

     ┌──────────────────────────────────────────────┐
     │ Observability / Experiments / Evaluation     │
     └──────────────────────────────────────────────┘

     ┌──────────────────────────────────────────────┐
     │ Language Packs / Linguistic Knowledge        │
     └──────────────────────────────────────────────┘
```

---

# 34. The strategic end state

The ultimate product should not be:

> "A swarm of seven AI agents that talks to you in another language."

It should be:

> **"A personal language-learning engine that continuously estimates what you can and cannot do, chooses the highest-value next learning activity, remembers your mistakes, adapts to your goals, and proves whether you are actually improving."**

That is the version of Polyglot Swarm that can credibly become **10/10 technically, pedagogically, and as a product**.

## Immediate next sprint

If starting tomorrow, implement only:

```text
Sprint 1
├── provider abstraction
├── SQLite persistence
├── user/session IDs
├── evidence event schema
├── learner-state schema
├── vocabulary mastery model
├── grammar evidence model
├── telemetry
└── end-to-end persistence test

Sprint 2
├── evaluator/verifier
├── structured outputs
├── grammar benchmark
├── vocabulary benchmark
├── false-correction benchmark
└── regression CI

Sprint 3
├── Next Best Learning Action
├── contextual FSRS
├── adaptive scenario difficulty
└── learner dashboard

Sprint 4
├── controlled learning experiment
├── delayed-retention tests
├── ablation study
└── publish benchmark report
```

**Do not add more agents until these foundations work.**

The existing repository's own implementation plan already identifies persistence, provider abstraction, missing agents, scenarios, analytics, API, voice and frontend as major gaps; this plan deliberately adds the missing **learner-model, evidence, verification, evaluation, and learning-outcome layers** that are necessary to move from an impressive architecture to a demonstrably superior tutor.
