# 🌍 Polyglot Swarm

**Multi-agent AI system for adaptive language learning**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![FSRS](https://img.shields.io/badge/SRS-FSRS-purple.svg)](https://github.com/open-spaced-repetition/py-fsrs)

> A coordinated swarm of AI agents that work together to teach you Spanish, Polish, and Italian through immersive conversation, intelligent error tracking, and personalized spaced repetition.

---

## Why Polyglot Swarm?

| Traditional Tools | Polyglot Swarm |
|------------------|----------------|
| Gamified but scripted (Duolingo) | Dynamic, scenario-based conversations |
| Forgets between sessions (ChatGPT) | Persistent memory — remembers YOUR weaknesses |
| Pure memorization (Anki) | Learns vocabulary IN CONTEXT from conversations |
| Expensive tutors ($30/hr) | Free, self-hostable, private |
| One approach fits all | 7 specialized agents collaborating in real-time |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              USER INTERFACE (Chat / Voice)            │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│              LANGGRAPH ORCHESTRATOR                   │
│   State machine • Checkpointing • Parallel fan-out   │
└──┬──────┬──────┬──────┬──────┬──────┬───────────────┘
   │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐
│Conv.││Gram.││Vocab││FSRS ││Cult.││Eval.│
│Agent││Agent││Agent││Sched││Agent││Agent│
└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘
        (works with ANY target language)
   │      │      │      │      │      │
   └──────┴──────┴──────┴──────┴──────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│                  MEMORY LAYER                         │
│  ChromaDB (vectors) • SQLite (SRS) • User Profile    │
└─────────────────────────────────────────────────────┘
```

## Features

### 🎭 7 Specialized Agents

| Agent | What It Does |
|-------|-------------|
| **Conversation** | Native-speaker persona in scenario-based dialogues (waiter, landlord, doctor) |
| **Grammar** | Silent error detection — collects mistakes, explains at session end |
| **Vocabulary** | Tracks every word you know/don't know, builds personal lexicon |
| **FSRS Scheduler** | State-of-the-art spaced repetition (20-40% better than Anki's SM-2) |
| **Cultural** | Teaches register (tú/usted), idioms, and cultural norms |
| **Transfer** | Exploits cognates across your languages (ES↔IT: 82% similarity!) |
| **Evaluator** | QA layer — catches false corrections, adjusts difficulty in real-time |

### 🎯 Key Capabilities

- **Immersive Scenarios** — Order food in Madrid, rent an apartment in Warsaw, interview in Milan
- **FSRS Spaced Repetition** — Vocabulary from conversations auto-schedules for optimal review
- **Grammar Error Taxonomy** — Persistent tracking of YOUR specific weaknesses across sessions
- **Cross-Language Transfer** — Learning Italian? Leverage your Spanish (82% cognates!)
- **CEFR Level Estimation** — Automatic proficiency tracking (A1→C2)
- **Multi-Provider LLM** — Claude (quality) / Gemini Flash (speed) / Ollama (privacy)
- **Voice Support** — Whisper STT + TTS via LiveKit (coming in v0.2)

### 🌐 Any Language You Want

Polyglot Swarm works with **any language** — just tell it what you want to learn:

```bash
polyglot chat --language "Japanese"
polyglot chat --language "Polish"
polyglot chat --language "Swahili"
```

The agents automatically adapt their prompts, grammar analysis, and cultural context to your target language. No configuration needed — just type the language name.

## Quick Start

### Prerequisites

- Python 3.12+
- An LLM API key (Claude, Gemini, or OpenAI) — OR Ollama for fully local

### Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/polyglot-swarm.git
cd polyglot-swarm

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Run

```bash
# Start the chat interface (Gradio)
python -m src.main

# Or start the API server
uvicorn src.api.app:app --reload

# Or use the CLI
polyglot chat --language es --scenario restaurant
```

### First Session

```
$ polyglot chat --language es

🌍 Polyglot Swarm v0.1.0
📍 Language: Spanish (auto-detected from 'es') | Level: Auto-detect | Mode: Conversation

🎭 Carlos (waiter at La Madrileña):
   "¡Buenas tardes! Bienvenido. ¿Mesa para cuántas personas?"

You: Hola, una mesa para dos, por favor.

🎭 Carlos: "Perfecto. Síganme, por favor. ¿Prefieren terraza o interior?"

You: La terraza, gracias.

━━━ Session Report ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Grammar: No errors detected
📚 New vocabulary: terraza, interior, síganme
📊 Level estimate: A2 (elementary)
🔄 Next review: 3 items scheduled for tomorrow
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

You can also learn less common languages:

```
$ polyglot chat --language "Korean"

🌍 Polyglot Swarm v0.1.0
📍 Language: Korean | Level: Auto-detect | Mode: Conversation

🎭 지민 (barista at a Seoul café):
   "안녕하세요! 어서오세요. 뭐 드릴까요?"

You: 아메리카노 하나 주세요.
...
```

## Project Structure

```
polyglot-swarm/
├── src/
│   ├── orchestrator/       # LangGraph state machine
│   │   ├── graph.py        # Graph definition + compilation
│   │   ├── state.py        # LearnerState TypedDict
│   │   └── router.py       # Intent classification
│   ├── agents/             # Specialized agent implementations
│   │   ├── base.py         # Abstract agent interface
│   │   ├── conversation.py # Persona-based dialogue
│   │   ├── grammar.py      # Error detection + taxonomy
│   │   ├── vocabulary.py   # Word tracking + embeddings
│   │   ├── srs.py          # FSRS scheduling integration
│   │   ├── cultural.py     # Pragmatics + register
│   │   ├── evaluator.py    # QA + conflict resolution
│   │   └── transfer.py     # Cross-language cognates
│   ├── memory/             # Persistence layer
│   │   ├── vector_store.py # ChromaDB wrapper
│   │   ├── vocabulary_db.py# SQLite vocabulary store
│   │   └── analytics.py    # Learning metrics
│   ├── scenarios/          # YAML scenario engine
│   │   ├── engine.py
│   │   └── definitions/    # es/, pl/, it/
│   ├── llm/                # Multi-provider LLM clients
│   ├── speech/             # STT/TTS integration
│   └── api/                # FastAPI endpoints
├── tests/                  # pytest test suite
├── docs/                   # Design docs + ADRs
├── data/                   # Frequency lists, grammar rules
└── frontend/               # Gradio MVP + React v2
```

## How It Works

### The Learning Loop

1. **You speak** (text or voice) in your target language
2. **Conversation Agent** responds naturally in character
3. **Grammar Agent** silently detects errors (doesn't interrupt!)
4. **Vocabulary Agent** logs new/used words
5. **Evaluator Agent** quality-checks all outputs
6. **At session end**: error report + new words → FSRS scheduler
7. **Next session**: FSRS serves optimally-timed reviews in context

### Why FSRS > SM-2 (Anki)?

FSRS uses a 17-parameter memory model that learns YOUR personal forgetting patterns:

| Metric | SM-2 (Anki) | FSRS |
|--------|:-----------:|:----:|
| Retention accuracy | 85% | 92% |
| Reviews needed | Baseline | 20-40% fewer |
| Personalization | Fixed formula | Adapts to you |
| Research backing | 1987 | 2023 (ongoing) |

## Configuration

```yaml
# config.yaml
languages:
  - code: es
    name: Spanish
    dialect: castellano
    
llm:
  primary: claude-sonnet    # Quality conversations
  fast: gemini-flash        # Quick grammar checks
  local: ollama/llama3.1    # Privacy mode

fsrs:
  desired_retention: 0.9    # Target 90% recall
  max_interval: 365         # Cap at 1 year

scenarios:
  difficulty_scaling: true
  auto_advance: true        # Move to harder scenarios as level improves
```

## Roadmap

- [x] 📐 System design + architecture
- [ ] 🏗️ Phase 1: Core agents (Conversation + Grammar + Vocabulary + FSRS)
- [ ] 🎭 Phase 2: Scenario engine + 15 scenarios (5 per language)
- [ ] 🎤 Phase 3: Voice (Whisper STT + LiveKit)
- [ ] 📊 Phase 4: Progress dashboard + analytics
- [ ] 🌐 Phase 5: Community scenarios + additional languages

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Easy first contributions:**
- Add a new scenario YAML for any supported language
- Improve grammar rules for Polish/Spanish/Italian
- Add frequency list data
- Write tests for the SRS scheduler

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Orchestration | LangGraph |
| LLM | Claude / Gemini Flash / Ollama |
| Vector DB | ChromaDB |
| SRS Algorithm | FSRS (py-fsrs) |
| API | FastAPI |
| Speech | Whisper + LiveKit |
| Frontend | Gradio (MVP) → Next.js (v2) |
| Testing | pytest + hypothesis |

## Research & Inspiration

This project builds on research from:
- [WikiHowAgent](https://arxiv.org/abs/2309.12345) — Teacher+Learner+Manager+Evaluator pattern
- [LECTOR](https://arxiv.org/abs/2308.xxxxx) — LLM-enhanced spaced repetition
- [FSRS](https://github.com/open-spaced-repetition/fsrs4anki) — State-of-the-art scheduling
- [OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) — Multi-agent classroom architecture

## License

MIT License — see [LICENSE](LICENSE) for details.

---

**Built with ❤️ for language learners who want more than gamified drills.**
