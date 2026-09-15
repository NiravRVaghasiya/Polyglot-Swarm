# 🌍 Polyglot Swarm

**A self-hostable, multi-agent AI language tutor that models what you can and can't do — and picks the highest-value thing to practice next.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![FSRS](https://img.shields.io/badge/SRS-FSRS-purple.svg)](https://github.com/open-spaced-repetition/py-fsrs)

> Polyglot Swarm holds scenario-based conversations in your target language, silently tracks your grammar and vocabulary as structured evidence, maintains a per-skill model of your competence, and uses that model to schedule reviews and choose your next activity. It runs fully local if you want it to.

---

## What it actually does

- **Scenario conversations** — role-play a waiter, landlord, doctor, or a free-form chat, in any language you name.
- **Silent, calibrated correction** — grammar deviations are detected, classified (wrong / awkward / regional / informal / acceptable), and only surfaced when the tutor is confident. Uncertain calls are *abstained*, not asserted — a false correction is treated as worse than a missed one.
- **A persistent learner model** — evidence from every turn updates per-skill mastery beliefs (grammar, vocabulary, speaking, listening, reading, writing, pragmatics), each with an uncertainty and sample size. This is the core of the system, not the number of agents.
- **Next-best-action planning** — a deterministic curriculum planner ranks what to practice by expected learning value, subject to due reviews, weaknesses, and a time budget.
- **FSRS spaced repetition** — vocabulary learned in conversation is scheduled with the real `py-fsrs` scheduler; reviews measure actual recall and feed it back into the model.
- **Multidimensional CEFR** — a per-skill CEFR profile with confidence, not a single made-up number.
- **Cross-language transfer** — cognates and false friends across your languages, retrieved from linguistic resources and verified by the model.
- **Voice** — microphone → Whisper STT → conversation → Edge TTS, in both the Gradio app and the React app (optional `voice` extra; degrades to text-only when absent).
- **Observability** — every model decision is correlated by an interaction id and reconstructable as a trace; cost/latency/tokens are tracked per call.
- **Privacy** — set `LOCAL_ONLY=true` and no learning data leaves your machine, regardless of which API keys are configured.

For the current measured numbers (component benchmarks, evaluation suites, and the component-ablation study), see [`docs/results.md`](docs/results.md) — regenerate it any time with `make results`.

## Architecture

```
                USER  (text / voice / React / Gradio / CLI)
                  │
                  ▼
        FastAPI + auth  ──►  LangGraph orchestrator (SQLite-checkpointed)
                  │
                  ▼
          Conversation engine
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
  Grammar     Vocabulary    Cultural        →  Evaluator / Verifier
  analysis     analysis     analysis           (accept / revise / abstain)
     └────────────┼────────────┘
                  ▼
          Evidence pipeline  (what happened, not what we believe)
                  │
                  ▼
        Learner Knowledge Model  (per-skill mastery + uncertainty)
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
  Assessment   Curriculum    FSRS
   (CEFR)      / planner    scheduler
     └────────────┼────────────┘
                  ▼
          Next best learning action  ──►  USER

  Cross-cutting: observability/tracing · evaluation harness · experiment
  platform · language packs · safety/verifier · security/privacy
```

See [`docs/architecture.md`](docs/architecture.md) for how these layers actually fit together in code.

## Quick start

### Prerequisites

- Python 3.12+
- At least one of: an LLM API key (Anthropic / Google / OpenAI), a local Ollama endpoint, or `POLYGLOT_DETERMINISTIC=1` for a fully offline demo.

### Install

```bash
git clone https://github.com/NiravRVaghasiya/Polyglot-Swarm.git
cd Polyglot-Swarm

pip install -e ".[dev]"        # add ".[voice]" or ".[all]" for STT/TTS

cp .env.example .env           # set an LLM key, or OLLAMA_BASE_URL, or leave it for deterministic mode
```

All configuration is environment variables (loaded from `.env` via pydantic-settings) — see [`.env.example`](.env.example) for the full list and [`docs/deployment.md`](docs/deployment.md) for details.

### Run

```bash
# Terminal chat (any language by name, or a scenario by id)
polyglot chat --language Spanish
polyglot chat --scenario es_restaurant_ordering
polyglot scenarios                         # list scenario ids

# Gradio app (chat + voice)
python -m src.main

# REST API (see http://localhost:8000/docs)
uvicorn src.api.app:app --reload

# React dashboard (separate Next.js app)
cd frontend/react_app && npm install && npm run dev
```

Check your configuration and provider health at any time:

```bash
polyglot health
```

### The CLI

Beyond `chat`, the `polyglot` command exposes the learner model and operations directly:

| Command | What it does |
|---|---|
| `polyglot plan` | Show the next-best-action learning plan |
| `polyglot assess` | Show the multidimensional CEFR profile |
| `polyglot progress` | Progress overview + streaks |
| `polyglot drill` / `write` / `peer` / `ingest` | Targeted drills, writing feedback, peer dialogue, external-text ingestion |
| `polyglot trace <session_id>` | Reconstruct a session as a full trace |
| `polyglot cost session/user` | LLM cost and latency, scoped to a session or user |
| `polyglot experiment ...` | Run the ablation study, assign variants, record/measure outcomes |
| `polyglot privacy export/delete` | Export or permanently delete your own data |
| `polyglot security backup/audit` | Database backups and the audit log |
| `polyglot results` | Regenerate `docs/results.md` from the measurement harnesses |

## Docker

```bash
cp .env.example .env
docker compose up                       # API (:8000) + Gradio UI (:7860)
docker compose --profile local-llm up   # also start an Ollama container (:11434)
```

## How the learning loop works

1. You send a message (text or voice) in your target language.
2. The **conversation** agent replies in character; **grammar**, **vocabulary**, and **cultural** agents analyze your input in parallel without interrupting.
3. The **evaluator/verifier** QAs those outputs — accepting, revising, or abstaining on each correction, and reconciling grammar-vs-culture conflicts.
4. Kept observations become structured **evidence**, which updates the **learner model** (per-skill mastery + uncertainty).
5. At session end you get a report; new vocabulary is scheduled with **FSRS**, and your **CEFR profile** is recomputed.
6. Next session, the **curriculum planner** uses the model to choose what's worth practicing, and FSRS surfaces due reviews in context.

## Measured results

The project ships three measurement harnesses — component benchmarks, evaluation
suites, and a component-ablation study — and a generator that runs them and writes
[`docs/results.md`](docs/results.md). The numbers below are the latest run
(`make results`).

> **Read this first.** These numbers are produced in **deterministic mode**
> (`POLYGLOT_DETERMINISTIC=1`), where LLM calls resolve to a reproducible
> fake/scripted provider. They validate the *machinery, decision logic, and
> pipeline wiring* — **not** live-model quality. Live-model precision, recall,
> and latency will differ, and no study with real learners has been run yet.
> The full caveats live in [`docs/results.md`](docs/results.md#known-limitations).

**Component benchmarks** — all pass:

| Benchmark | Key metrics |
|---|---|
| `grammar_precision` | precision 1.000 · recall 1.000 · false-correction-rate 0.000 (8 cases) |
| `verifier_calibration` | ECE 0.000 (30 predictions) |
| `structured_output_parseable` | valid JSON ✓ |
| `provider_latency` | round-trips through the provider layer ✓ |

**Evaluation suites** — 11/11 pass, e.g. grammar F1 1.000 (FCR 0.000, 17 cases),
vocabulary extraction F1 1.000, assessment CEFR correlation 1.000 / band-MAE 0.000,
curriculum target-coverage 1.000, and a regression gate over all rolled-up suites.

**Ablation study** — which architectural components actually create the
learner-model signal. Metric is mean grammar+vocabulary mastery gain over one
scripted session:

| Arm | Description | Mastery gain |
|---|---|---|
| A | conversation only | +0.000 |
| B | conversation + memory | +0.000 |
| C | conversation + FSRS review | +0.000 |
| D | conversation + analysis (learner model) | **+0.333** |
| E | full system | **+0.333** |

The arms *without* the analysis pipeline (A/B/C) accumulate no learner-model
evidence and show zero gain; the arms *with* it (D/E) show a positive gain — the
intended result: the analysis components are what turn a conversation into
measurable evidence about the learner.

Regenerate everything with `make results` (or `polyglot results`).

## Languages

The generic agents work with **any language you name** — just pass it to `chat` or the API. Three languages additionally ship a **language pack** (Spanish, Polish, Italian) with a grammar-construction taxonomy, frequency list, collocations, register notes, and cross-language transfer data. Adding resources for a new language is data, not code — see [`docs/language-packs.md`](docs/language-packs.md).

Fifteen scenarios ship across the three packs (restaurant, pharmacy, job interview, and more).

## Documentation

Grounded in the actual implementation:
[architecture](docs/architecture.md) · [learner model](docs/learner-model.md) ·
[evaluation](docs/evaluation.md) · [language packs](docs/language-packs.md) ·
[LLM providers](docs/providers.md) · [privacy](docs/privacy.md) ·
[deployment](docs/deployment.md) · [measured results](docs/results.md) ·
[ADR log](docs/adr/README.md).

`docs/DESIGN.md` and `docs/RESEARCH.md` are the original product research and vision — kept for history, not a spec.

## Development

The `Makefile` is the single source of truth for build/test/quality gates; CI runs the same targets.

```bash
make check       # lint + format-check + typecheck + test (the full local gate)
make test        # pytest, deterministic + offline (no API keys, no network)
make benchmark   # component benchmarks
make eval        # evaluation suites (grammar/vocabulary/assessment/curriculum/regression)
make results     # regenerate docs/results.md
```

The test suite runs fully offline in deterministic mode (`POLYGLOT_DETERMINISTIC=1`), which routes every LLM call to a reproducible fake provider — no keys or network required.

## Tech stack

| Component | Technology |
|-----------|-----------|
| Orchestration | LangGraph (SQLite checkpointer) |
| LLM providers | Claude / Gemini / OpenAI / Ollama, tiered routing with retry + circuit breaker |
| Relational store | SQLite (source of truth) |
| Vector store | ChromaDB (semantic memory) |
| Spaced repetition | FSRS (`py-fsrs`) |
| API | FastAPI |
| Voice | Whisper (STT) + Edge TTS, optional LiveKit transport |
| Frontends | Gradio (MVP) + Next.js / React (dashboard) |
| Tooling | ruff, mypy (strict), pytest |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow,
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations, and
[SECURITY.md](SECURITY.md) to report a vulnerability privately. Structural changes
should come with an [ADR](docs/adr/README.md).

Good first contributions: add a scenario YAML, extend a language pack's grammar/frequency data, or add tests.

## License

MIT — see [LICENSE](LICENSE).

---

**Built for language learners who want a tutor that remembers, not a chatbot that forgets.**
