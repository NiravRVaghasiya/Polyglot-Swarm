# Polyglot Swarm — System Design Document

> **Version:** 1.1 (updated with competitive research)  
> **Author:** Nirav Vaghasiya  
> **Date:** June 17, 2026  
> **Status:** Draft  

---

## 1. Executive Summary

**Polyglot Swarm** is a multi-agent AI system for adaptive language learning. Unlike Duolingo's gamified but shallow approach, it deploys a coordinated swarm of specialized agents that simulate immersive conversation, track individual weaknesses, and adapt in real time — creating a personalized language tutor that remembers everything.

**Target languages (v1):** Spanish, Polish, Italian  
**Target user:** Intermediate learners (A2–B2 CEFR) who want conversation fluency, not just vocabulary drills.

---

## 2. Competitive Landscape & Positioning

### 2.1 Market Gap Analysis

Research across 10 open-source projects, 8 commercial products, and 6 academic papers reveals a clear gap:

**No open-source project combines:** Multi-agent architecture + Integrated spaced repetition + Grammar weakness tracking + Voice + European language focus (especially Polish).

| Capability | Immergo | OpenMAIC | Speak | Langua | Duolingo | **Polyglot Swarm** |
|-----------|:-------:|:--------:|:-----:|:------:|:--------:|:-----------------:|
| Multi-agent architecture | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Spaced repetition | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ (FSRS) |
| Voice-first | ✅ | ✅ | ✅✅ | ✅ | Basic | ✅ (LiveKit) |
| Grammar error taxonomy | ❌ | ❌ | ✅ | ✅ | Basic | ✅✅ |
| Cross-session memory | ❌ | ❌ | ✅ | ✅ | ✅ | ✅✅ |
| European language focus | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (PL/ES/IT specific) |
| Open-source | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Self-hostable / local | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ |

### 2.2 Key Competitors

| Competitor | Strength | Our Differentiation |
|-----------|----------|-------------------|
| **Speak** ($500M) | Best voice UX, hybrid ASR↔LLM↔TTS pipeline | Open-source, multi-agent, grammar taxonomy, self-hostable |
| **Langua** | Most complete ecosystem (conversation→vocab→flashcards→stories) | Multi-agent coordination, FSRS (superior algorithm), Polish-specific modules |
| **OpenMAIC** (18.7K⭐) | Multi-agent classroom, 15+ LLM providers | Language-learning-specific pedagogy (OpenMAIC is general education) |
| **Duolingo Max** | Massive scale, gamification, habit-building | Deeper conversations, persistent error memory, no subscription wall |
| **FSRS** (3.2K⭐) | State-of-the-art scheduling algorithm | We integrate FSRS into a full learning system (FSRS alone is just an algorithm) |
| **Immergo** (458⭐) | Voice roleplay with Gemini Live | Multi-agent, vocabulary tracking, grammar correction, persistence, multi-provider |

### 2.3 Open-Source Building Blocks to Integrate

| Component | Source | How We Use It |
|-----------|--------|---------------|
| **FSRS algorithm** | [open-spaced-repetition/py-fsrs](https://github.com/open-spaced-repetition) | Core scheduling engine for vocabulary + grammar review |
| **LangGraph** | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | Agent orchestration, state management, checkpointing |
| **LiveKit Agents** | [livekit/agents](https://github.com/livekit/agents) | Voice transport layer (WebRTC, turn detection, echo cancellation) |
| **Chiron pattern** | [NirDiamant/GenAI_Agents](https://github.com/NirDiamant/GenAI_Agents) | LangGraph education agent reference architecture |
| **Whisper** | [openai/whisper](https://github.com/openai/whisper) | Speech-to-text (local, handles non-native accents) |

### 2.4 Insights from Research Papers

| Paper | Key Pattern Adopted |
|-------|-------------------|
| **WikiHowAgent** (Sep 2025) | Teacher + Learner + Manager + Evaluator → maps to our Conversation + Grammar + Orchestrator + Assessment agents |
| **LECTOR** (Aug 2025) | LLM-enhanced spaced repetition: detect semantically confusable word pairs, schedule around them |
| **CogEvo-Edu** (Dec 2025) | Hierarchical cognitive layers: Perception → Knowledge Evolution → Meta-Control |
| **ITAS** (Apr 2026) | Production multi-agent tutoring: content grounding, safety guardrails, graceful degradation |
| **GenMentor** (Jan 2025) | Goal-to-skill mapping: "order food in Spanish" → {vocabulary, verb conjugation, pronunciation} |

### 2.5 7 Key Gaps We Exploit

1. **Multi-Agent + Language Pedagogy** — OpenMAIC is multi-agent but general; Speak has pedagogy but is single-agent and closed
2. **Integrated SRS + Conversation** — Every tool does ONE well; none deeply integrates both (vocabulary from conversation → personalized review schedule → practice IN CONTEXT)
3. **Grammar Error Taxonomy** — No tool builds a persistent learner model of specific grammar weaknesses across sessions
4. **European Language Modules** — No open-source tool provides specialized Polish morphology (7 cases, aspect pairs), Spanish ser/estar, Italian passato/imperfetto
5. **Conversation Memory** — Sessions reset everywhere; no persistent learner graph informing every interaction
6. **Open-Source Voice-First** — Commercial-only (Speak, Langua); no serious open-source with hybrid ASR pipeline
7. **Privacy-Preserving** — All commercial products require cloud; we support local-first with Ollama

---

## 2. Problem Statement

| Current Tools | Limitation |
|--------------|------------|
| Duolingo / Babbel | Gamified but scripted; no real conversation practice; no persistent error memory |
| ChatGPT / Claude chat | Good conversation but no structured curriculum, no SRS, forgets between sessions |
| Anki / flashcard apps | Pure memorization; no contextual usage, no grammar correction |
| iTalki / tutors | Expensive ($15–40/hr); scheduling friction; no persistent progress tracking |

**Gap:** No tool combines *adaptive conversation* + *persistent memory* + *spaced repetition* + *grammar intelligence* + *cultural awareness* in a single coordinated system.

---

## 3. System Architecture

### 3.1 High-Level Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                             │
│    (Chat UI — Web/CLI — Voice via LiveKit WebRTC)                 │
└─────────────────────┬────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                 LANGGRAPH ORCHESTRATOR                            │
│  • Graph-based state machine with checkpointing                  │
│  • Persistent session state (survives disconnects)               │
│  • Intent classification                                         │
│  • Agent dispatch & coordination                                 │
│  • Session state management                                      │
│  • Mode selection (conversation / drill / review / assessment)   │
└──────┬──────────┬──────────┬──────────┬──────────┬─────────────┘
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│Conversa- │ │ Grammar  │ │Vocabulary│ │   FSRS   │ │ Cultural │
│tion Agent│ │  Agent   │ │  Agent   │ │Scheduler │ │  Agent   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
       │          │          │          │          │
       └──────────┴──────────┴──────────┴──────────┘
                             │
                    ┌────────┴────────┐
                    │ Evaluator Agent │ (WikiHowAgent pattern)
                    └────────┬────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY LAYER                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ User Profile │  │ Vector Store│  │ Learning History (SRS)  │ │
│  │ (CEFR, goals)│  │ (ChromaDB)  │  │ (SQLite + SM-2)        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLM PROVIDERS                                │
│  Claude API (quality) | Gemini Flash (speed) | Ollama (privacy)  │
│  Multi-provider routing with intelligent failover                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Interaction Flow

```
User: "Quiero practicar pedir comida en un restaurante"

1. Orchestrator → classifies intent: CONVERSATION_MODE + SCENARIO(restaurant)
2. Orchestrator → activates: ConversationAgent(persona=waiter), GrammarAgent, VocabularyAgent
3. ConversationAgent → generates response in character (Spanish waiter)
4. User responds → all agents process in parallel:
   - GrammarAgent → detects errors, stores silently
   - VocabularyAgent → logs new words used, checks comprehension
   - ConversationAgent → continues dialogue naturally
5. End of scenario:
   - GrammarAgent → surfaces error report with corrections
   - VocabularyAgent → adds new items to SRS queue
   - SRS Agent → schedules next reviews based on SM-2
   - Cultural Agent → adds note on tipping customs in Spain
```

---

## 4. Agent Specifications

### 4.1 Conversation Agent

| Property | Detail |
|----------|--------|
| **Role** | Simulates a native speaker in scenario-based dialogues |
| **Personas** | Waiter, landlord, colleague, doctor, shopkeeper, interviewer (configurable via YAML) |
| **Input** | User text/voice + current scenario context + user CEFR level |
| **Output** | Natural target-language response, calibrated to user level |
| **Behavior** | Never breaks character; adjusts complexity dynamically; asks follow-up questions |

```yaml
# Example persona definition
persona:
  name: "María"
  role: "waitress"
  language: "es"
  location: "Madrid"
  personality: "friendly, slightly impatient during rush hour"
  vocabulary_level: "B1"
  dialect: "castellano"
  topics: ["food", "drinks", "recommendations", "billing"]
```

### 4.2 Grammar Agent

| Property | Detail |
|----------|--------|
| **Role** | Silent error detection + post-conversation correction |
| **Input** | User's raw text + target language + known grammar rules |
| **Output** | Structured error report: `{error, correction, rule, explanation, severity}` |
| **Behavior** | Does NOT interrupt conversation flow; collects errors; surfaces at end |

**Error taxonomy:**
```python
class GrammarError:
    original: str  # "Yo soy tiene hambre"
    correction: str  # "Yo tengo hambre"
    rule: str  # "ser_vs_tener"
    explanation: str  # "Use 'tener' for physical states (hunger, thirst, cold)"
    severity: Literal["minor", "moderate", "critical"]
    frequency: int  # how many times user has made this error
    cefr_level: str  # at which level this should be mastered
```

### 4.3 Vocabulary Agent

| Property | Detail |
|----------|--------|
| **Role** | Tracks known/unknown words; builds personal lexicon |
| **Input** | Conversation text + user's vocabulary database |
| **Output** | New word entries, usage frequency updates, gap analysis |
| **Behavior** | Maintains per-user vocabulary graph with relationships |

**Data model:**
```python
class VocabularyEntry:
    word: str  # "restaurante"
    language: str  # "es"
    translation: str  # "restaurant"
    pos: str  # "noun"
    cefr_level: str  # "A1"
    contexts: list[str]  # sentences where user encountered it
    times_seen: int
    times_used_correctly: int
    times_used_incorrectly: int
    last_reviewed: datetime
    next_review: datetime  # SM-2 scheduled
    related_words: list[str]  # cognates in other target languages
    embedding: list[float]  # for semantic similarity search
```

### 4.4 Spaced Repetition (SRS) Agent

| Property | Detail |
|----------|--------|
| **Role** | Schedules optimal review timing using FSRS algorithm |
| **Input** | User's vocabulary + grammar errors + review history |
| **Output** | Review queue sorted by urgency; context-rich flashcards |
| **Algorithm** | FSRS (Free Spaced Repetition Scheduler) — state-of-the-art, superior to SM-2 |

**Why FSRS over SM-2:**
- FSRS uses a 17-parameter DSR (Difficulty, Stability, Retrievability) memory model
- Learns individual memory patterns (personalizes to each user)
- Proven 20–40% more efficient than SM-2 in retention studies
- Already integrated into Anki (millions of users validate it)
- Open-source Python implementation available (`py-fsrs`)

**FSRS integration:**
```python
from fsrs import FSRS, Card, Rating

scheduler = FSRS()


def review_card(card: Card, rating: Rating) -> Card:
    """
    rating: Rating.Again (1), Hard (2), Good (3), Easy (4)

    FSRS internally tracks:
    - difficulty: inherent difficulty of the material
    - stability: memory stability (how long until forgetting)
    - retrievability: probability of recall at this moment
    """
    scheduling_cards = scheduler.repeat(card, datetime.now(timezone.utc))
    updated_card = scheduling_cards[rating].card
    review_log = scheduling_cards[rating].review_log
    return updated_card


# Enhanced: LLM-generated contextual review (from LECTOR paper insight)
def generate_contextual_review(word: str, language: str, user_context: dict) -> str:
    """
    Instead of flashcard: "restaurante = restaurant"
    Generate: "Complete: Ayer fui al ___ con mi familia" (contextual sentence)

    Also detects semantically confusable pairs:
    e.g., "ser" vs "estar" — schedules them in alternation to build distinction
    """
    confusable_pairs = find_confusable_words(word, user_context["vocabulary"])
    return llm_generate_review_sentence(word, confusable_pairs, user_context)
```

### 4.5 Cultural Context Agent

| Property | Detail |
|----------|--------|
| **Role** | Teaches register, pragmatics, idioms, cultural norms |
| **Input** | Conversation context + user's register usage |
| **Output** | Cultural notes, formality corrections, idiom explanations |
| **Behavior** | Flags tú/usted misuse; teaches when to use formal; explains idioms |

### 4.6 Cross-Language Transfer Agent

| Property | Detail |
|----------|--------|
| **Role** | Exploits similarities between user's target languages |
| **Input** | User's active languages (ES, PL, IT) + current vocabulary |
| **Output** | Cognate suggestions, false friend warnings, shared patterns |
| **Examples** | ES "restaurante" → IT "ristorante" → PL "restauracja" |

**Transfer matrix (Spanish ↔ Italian ↔ Polish):**
```
Spanish ↔ Italian:  ~82% lexical similarity (Romance family)
Spanish ↔ Polish:   ~10% (Indo-European distant)
Italian ↔ Polish:   ~10% (Indo-European distant)

Key transfers:
- ES/IT share: verb conjugation patterns, gendered nouns, similar prepositions
- PL unique: 7 grammatical cases, aspect pairs, consonant clusters
- All three: SVO word order (PL flexible), similar number systems
```

### 4.7 Assessment Agent

| Property | Detail |
|----------|--------|
| **Role** | Estimates CEFR level; adjusts system difficulty |
| **Input** | Aggregated data from all agents (errors, vocabulary, fluency) |
| **Output** | CEFR score (A1–C2) per skill (reading, writing, speaking, listening) |
| **Metrics** | Vocabulary breadth, grammar accuracy, response latency, complexity used |

### 4.8 Evaluator Agent (NEW — from WikiHowAgent pattern)

| Property | Detail |
|----------|--------|
| **Role** | Independent quality evaluator for all agent outputs |
| **Input** | Outputs from Conversation, Grammar, and Vocabulary agents |
| **Output** | Quality scores, correction overrides, pedagogical adjustments |
| **Behavior** | Acts as QA layer; catches when Grammar Agent is too strict or Conversation Agent is too advanced |

**Why a separate Evaluator (from research):**
The WikiHowAgent paper (Sep 2025) demonstrated that a 4-agent architecture with a dedicated evaluator significantly outperforms self-assessment. The evaluator:
- Catches grammar correction errors (false positives)
- Identifies when conversation difficulty drifts too high/low
- Resolves conflicts between agents (e.g., Grammar Agent wants formal, Cultural Agent says informal is fine in this context)
- Provides the "meta-cognitive" layer that keeps the system pedagogically sound

```python
class EvaluatorAgent:
    def evaluate_turn(self, turn_context: TurnContext) -> EvaluationResult:
        """
        Runs AFTER all other agents process a turn.
        Can override grammar corrections, adjust difficulty, or inject pedagogical notes.
        """
        grammar_quality = self.check_grammar_agent_accuracy(turn_context.grammar_output)
        difficulty_alignment = self.assess_difficulty_match(turn_context)
        conflict_resolution = self.resolve_agent_conflicts(turn_context)
        return EvaluationResult(overrides=..., adjustments=..., notes=...)
```

---

## 5. LangGraph State Machine Design

### 5.1 Graph State Schema

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from operator import add


class LearnerState(TypedDict):
    """Shared state across all agent nodes"""

    # Session
    session_id: str
    language: str
    mode: str  # "conversation", "review", "drill", "assessment"

    # Conversation
    messages: Annotated[list[dict], add]  # chat history (appended)
    current_scenario: dict | None

    # Agent outputs (updated per turn)
    grammar_errors: list[dict]  # from Grammar Agent
    new_vocabulary: list[dict]  # from Vocabulary Agent
    cultural_notes: list[str]  # from Cultural Agent
    evaluation: dict | None  # from Evaluator Agent

    # Persistent learner profile (loaded from DB at session start)
    cefr_level: str
    vocabulary_known: int
    grammar_weaknesses: list[str]
    interests: list[str]

    # Control flow
    turn_count: int
    should_end_session: bool
    pending_reviews: list[dict]  # FSRS due items
```

### 5.2 Graph Topology

```python
graph = StateGraph(LearnerState)

# Define nodes (agents)
graph.add_node("router", router_node)  # Intent → mode dispatch
graph.add_node("conversation", conversation_node)  # Generate response
graph.add_node("grammar", grammar_node)  # Analyze user input
graph.add_node("vocabulary", vocabulary_node)  # Track words
graph.add_node("cultural", cultural_node)  # Add cultural notes
graph.add_node("evaluator", evaluator_node)  # QA all outputs
graph.add_node("review", review_node)  # FSRS review session
graph.add_node("session_end", session_end_node)  # Compile report

# Edges
graph.set_entry_point("router")
graph.add_conditional_edges(
    "router",
    route_by_mode,
    {"conversation": "conversation", "review": "review", "end": "session_end"},
)

# After conversation response, fan out to analysis agents (parallel)
graph.add_edge("conversation", "grammar")
graph.add_edge("conversation", "vocabulary")
graph.add_edge("conversation", "cultural")

# All analysis feeds into evaluator
graph.add_edge("grammar", "evaluator")
graph.add_edge("vocabulary", "evaluator")
graph.add_edge("cultural", "evaluator")

# Evaluator loops back to router for next turn
graph.add_edge("evaluator", "router")
graph.add_edge("session_end", END)
```

---

## 5. Memory Layer Design

### 5.1 Storage Architecture

```
memory/
├── user_profiles/          # JSON — goals, native lang, CEFR, preferences
│   └── {user_id}.json
├── vocabulary_db/          # SQLite — per-user word bank + SRS metadata
│   └── vocab.db
├── grammar_errors/         # SQLite — error patterns, frequency, mastery
│   └── grammar.db
├── conversation_history/   # SQLite + embeddings — past sessions
│   └── history.db
├── vector_store/           # ChromaDB — semantic search over context
│   └── chroma/
└── learning_analytics/     # Time-series — progress, streaks, engagement
    └── analytics.db
```

### 5.2 Vector Store Schema (ChromaDB)

```python
# Collections
collections = {
    "vocabulary": {
        "documents": ["word + definition + example sentence"],
        "metadata": {"language", "cefr_level", "pos", "user_id"},
        "embeddings": "all-MiniLM-L6-v2",  # multilingual
    },
    "grammar_rules": {
        "documents": ["rule explanation + examples"],
        "metadata": {"language", "category", "cefr_level"},
    },
    "conversations": {
        "documents": ["conversation turns with context"],
        "metadata": {"scenario", "language", "date", "cefr_at_time"},
    },
    "cultural_notes": {
        "documents": ["cultural insight + when to apply"],
        "metadata": {"language", "region", "topic"},
    },
}
```

### 5.3 Learning Analytics Schema

```sql
CREATE TABLE learning_sessions (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    language TEXT,
    session_type TEXT,  -- conversation, drill, review, assessment
    duration_minutes REAL,
    words_practiced INTEGER,
    new_words_learned INTEGER,
    grammar_errors INTEGER,
    grammar_errors_corrected INTEGER,
    cefr_estimate TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE error_patterns (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    language TEXT,
    error_type TEXT,       -- "ser_vs_estar", "genitive_case", etc.
    occurrences INTEGER,
    last_occurrence DATETIME,
    mastered BOOLEAN DEFAULT FALSE,
    mastered_date DATETIME
);
```

---

## 6. Scenario Engine

### 6.1 Scenario Definition Format

```yaml
# scenarios/es/restaurant.yaml
scenario:
  id: "es_restaurant_ordering"
  title: "Ordering at a Restaurant"
  language: "es"
  cefr_min: "A2"
  cefr_max: "B2"
  location: "Madrid, Spain"
  
  personas:
    - id: "waiter"
      name: "Carlos"
      personality: "efficient, recommends daily specials"
      
  objectives:
    - id: "greet"
      description: "Greet and ask for a table"
      required_vocab: ["mesa", "reserva", "personas"]
    - id: "order_food"
      description: "Order a main course and drink"
      required_vocab: ["plato", "bebida", "cuenta"]
    - id: "handle_problem"
      description: "Handle a wrong order politely"
      required_vocab: ["disculpe", "pedí", "cambiar"]
      
  difficulty_scaling:
    A2: "Waiter speaks slowly, offers choices, accepts short answers"
    B1: "Normal speed, follow-up questions, minor complications"
    B2: "Fast speech, idioms, cultural references, ambiguous situations"
    
  success_criteria:
    - all_objectives_completed: true
    - grammar_error_rate: "<20%"
    - used_target_vocabulary: ">60%"
```

### 6.2 Scenario Library (v1)

| Language | Scenarios |
|----------|-----------|
| **Spanish** | Restaurant, Airport, Doctor visit, Job interview, Phone call, Shopping, Renting apartment |
| **Polish** | Sklep spożywczy, Urząd (office), Lekarz, Rozmowa kwalifikacyjna, Transport publiczny, Sąsiad |
| **Italian** | Bar/Caffè, Mercato, Farmacia, Colloquio di lavoro, Stazione, Affittare casa |

---

## 7. API Design

### 7.1 Core Endpoints

```python
# FastAPI application structure

# --- Session Management ---
POST / api / v1 / sessions / start  # Start new learning session
GET / api / v1 / sessions / {id} / state  # Get current session state
POST / api / v1 / sessions / {id} / end  # End session, trigger reports

# --- Conversation ---
POST / api / v1 / chat  # Send message, get agent response
# Request: { session_id, message, language, mode }
# Response: { reply, hidden_feedback: {grammar, vocab, cultural} }

# --- Review & Drills ---
GET / api / v1 / review / due  # Get cards due for review
POST / api / v1 / review / submit  # Submit review answer
GET / api / v1 / drills / generate  # Generate targeted drill

# --- Progress ---
GET / api / v1 / progress / overview  # CEFR estimates, streaks, stats
GET / api / v1 / progress / vocabulary  # Vocabulary growth over time
GET / api / v1 / progress / weaknesses  # Top grammar/vocab gaps

# --- Scenarios ---
GET / api / v1 / scenarios  # List available scenarios
POST / api / v1 / scenarios / {id} / start  # Start a scenario session

# --- User Profile ---
GET / api / v1 / profile  # User settings, goals, languages
PUT / api / v1 / profile  # Update preferences
```

### 7.2 Internal Agent Communication Protocol

```python
from pydantic import BaseModel
from typing import Literal


class AgentMessage(BaseModel):
    """Internal message format between agents"""

    source_agent: str  # "grammar_agent"
    target_agent: str  # "orchestrator" or "broadcast"
    message_type: Literal[
        "error_detected",
        "new_vocabulary",
        "level_change",
        "scenario_objective_met",
        "review_scheduled",
        "cultural_note",
    ]
    payload: dict  # agent-specific data
    priority: Literal["low", "medium", "high"]
    timestamp: datetime
    session_id: str


class AgentResponse(BaseModel):
    """What each agent returns to the orchestrator"""

    agent_name: str
    user_facing_output: str | None  # None = silent processing
    internal_state_update: dict  # what to persist
    triggers: list[AgentMessage]  # messages to other agents
```

---

## 8. Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Language** | Python 3.12+ | ML ecosystem, FastAPI, your expertise |
| **Framework** | FastAPI | Async, typed, fast, lightweight |
| **Agent orchestration** | LangGraph | Proven at scale (Klarna, LinkedIn, Uber), checkpointing, human-in-the-loop, graph state |
| **LLM (quality)** | Claude API | Best at nuanced language, instruction-following, persona maintenance |
| **LLM (speed)** | Gemini Flash | Low latency for real-time conversation, cheap for high-volume |
| **LLM (privacy/offline)** | Ollama + Llama 3.1 8B | Local-first mode, no data leaves device |
| **Vector DB** | ChromaDB | Simple, embedded, good for <100K docs |
| **Relational DB** | SQLite | Zero-config, sufficient for single-user MVP |
| **SRS Algorithm** | FSRS (`py-fsrs`) | State-of-the-art, 20-40% more efficient than SM-2, personalized |
| **Embeddings** | `multilingual-e5-small` | Superior multilingual support (ES/PL/IT), runs locally |
| **Speech-to-Text** | Whisper (local) or Deepgram (cloud) | Whisper: free, handles accents; Deepgram: lower latency |
| **Text-to-Speech** | Edge TTS / ElevenLabs | Edge: free, good quality; ElevenLabs: premium voice cloning |
| **Voice Transport** | LiveKit Agents | WebRTC, echo cancellation, turn detection (used by Speak) |
| **Frontend (MVP)** | Gradio | Rapid prototyping, chat + audio interface built-in |
| **Frontend (v2)** | Next.js + Tailwind | Production UI with progress dashboards, PWA |
| **Deployment** | Docker → EC2 / local | Flexible |
| **Testing** | pytest + hypothesis | Property-based testing for SRS logic |

---

## 9. Data Flow Diagrams

### 9.1 Conversation Turn Flow

```
┌──────┐    message     ┌──────────────┐
│ User │ ──────────────→│ Orchestrator │
└──────┘                └──────┬───────┘
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                    ▼          ▼          ▼
            ┌───────────┐ ┌────────┐ ┌──────────┐
            │Conversation│ │Grammar │ │Vocabulary│  (parallel)
            │   Agent    │ │ Agent  │ │  Agent   │
            └─────┬─────┘ └───┬────┘ └────┬─────┘
                  │            │           │
                  ▼            ▼           ▼
            ┌─────────┐  ┌─────────┐ ┌─────────┐
            │ Reply to │  │ Errors  │ │New words│
            │   user   │  │(stored) │ │(stored) │
            └─────────┘  └─────────┘ └─────────┘
                  │
                  ▼
            ┌──────┐
            │ User │  (sees only the reply; errors revealed at session end)
            └──────┘
```

### 9.2 End-of-Session Flow

```
Session ends
    │
    ├─→ Grammar Agent: compile error report → display to user
    ├─→ Vocabulary Agent: new words → SRS Agent (schedule reviews)
    ├─→ Assessment Agent: recalculate CEFR estimate
    ├─→ Analytics: log session metrics
    └─→ Cross-Language Agent: suggest cognates from other languages
```

---

## 10. CEFR Level Estimation

### 10.1 Metrics Used

```python
class CEFRMetrics:
    # Vocabulary
    unique_words_used: int  # A1:500, A2:1000, B1:2000, B2:4000
    avg_word_frequency_rank: float  # lower = more advanced words

    # Grammar
    clause_complexity: float  # subordinate clauses per sentence
    tense_variety: set[str]  # {"present", "past", "subjunctive", ...}
    error_rate: float  # errors per 100 words

    # Fluency
    avg_response_length: float  # words per turn
    hesitation_markers: float  # "um", "eh" in speech

    # Comprehension
    comprehension_accuracy: float  # on reading/listening tasks
```

### 10.2 Level Thresholds

| Level | Vocab Size | Grammar Accuracy | Tenses Used | Response Length |
|-------|-----------|-----------------|-------------|----------------|
| A1 | <500 | >80% (simple) | present only | 3–8 words |
| A2 | 500–1000 | >70% | present + past | 8–15 words |
| B1 | 1000–2000 | >65% | + future, conditional | 15–25 words |
| B2 | 2000–4000 | >70% (complex) | + subjunctive | 25–40 words |
| C1 | 4000–8000 | >80% (complex) | all tenses + nuance | 40+ words |

---

## 11. Project Structure

```
polyglot-swarm/
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
│
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry + LangGraph compilation
│   ├── config.py                  # Settings, env vars
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── graph.py              # LangGraph state machine definition
│   │   ├── state.py              # LearnerState TypedDict + reducers
│   │   ├── router.py             # Intent classification → mode routing
│   │   └── coordinator.py        # Multi-agent coordination logic
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py               # Abstract agent interface
│   │   ├── conversation.py       # Conversation partner agent
│   │   ├── grammar.py            # Grammar detection + correction
│   │   ├── vocabulary.py         # Vocabulary tracking
│   │   ├── srs.py                # Spaced repetition scheduling
│   │   ├── cultural.py           # Cultural/pragmatic notes  
│   │   ├── evaluator.py          # QA layer (WikiHowAgent pattern)
│   │   ├── transfer.py           # Cross-language transfer
│   │   └── assessment.py         # CEFR level estimation
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── user_profile.py       # User settings & goals
│   │   ├── vector_store.py       # ChromaDB wrapper
│   │   ├── vocabulary_db.py      # SQLite vocabulary store
│   │   ├── session_history.py    # Conversation logs
│   │   └── analytics.py          # Learning metrics
│   │
│   ├── scenarios/
│   │   ├── __init__.py
│   │   ├── engine.py             # Scenario runner
│   │   ├── loader.py             # YAML scenario parser  
│   │   └── definitions/          # Scenario YAML files
│   │       ├── es/
│   │       │   ├── restaurant.yaml
│   │       ├── pl/
│   │       │   ├── sklep.yaml
│   │       └── it/
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── provider.py           # Abstract LLM interface
│   │   ├── claude.py             # Claude API client
│   │   ├── ollama.py             # Local LLM client
│   │   ├── gemini.py             # Gemini Flash client (speed tier)
│   │   └── prompts/              # Jinja2 system prompts per agent
│   │       ├── conversation.jinja2
│   │       ├── grammar.jinja2
│   │       └── ...
│   │
│   ├── speech/
│   │   ├── __init__.py
│   │   ├── stt.py                # Whisper speech-to-text
│   │   ├── tts.py                # Text-to-speech (Edge/ElevenLabs)
│   │   └── livekit_agent.py      # LiveKit voice transport integration
│   │
│   ├── scheduling/
│   │   ├── __init__.py
│   │   └── tts.py                # Text-to-speech
│   │
│   └── api/
│       ├── __init__.py
│       ├── routes/
│       │   ├── chat.py
│       │   ├── review.py
│       │   ├── progress.py
│       │   └── scenarios.py
│       └── schemas.py            # Pydantic request/response models
│
├── tests/
│   ├── test_agents/
│   ├── test_memory/
│   ├── test_fsrs/                 # FSRS scheduling tests
│   ├── test_graph/                # LangGraph state transition tests
│   ├── test_grammar/              # Language-specific grammar rule tests
│   └── test_scenarios/
│
├── data/
│   ├── frequency_lists/          # Word frequency data per language
│   ├── grammar_rules/            # Structured grammar rule definitions
│   └── seed_scenarios/           # Initial scenario templates
│
└── frontend/
    ├── gradio_app.py             # MVP chat + voice interface
    └── react_app/                # v2 production UI
```

---

## 12. Implementation Roadmap

### Phase 1 — Core Loop (Weeks 1–3)
- [ ] Project scaffolding + FastAPI setup
- [ ] Base agent interface + orchestrator
- [ ] Conversation Agent (Claude API, single persona)
- [ ] Grammar Agent (error detection + report)
- [ ] Vocabulary Agent (SQLite tracking)
- [ ] SRS Agent (SM-2 algorithm)
- [ ] Gradio chat UI
- [ ] Basic session management

### Phase 2 — Intelligence (Weeks 4–6)
- [ ] Scenario engine (YAML definitions)
- [ ] 5 scenarios per language (ES, PL, IT)
- [ ] Cross-language transfer agent
- [ ] CEFR assessment agent
- [ ] ChromaDB vector memory integration
- [ ] Learning analytics dashboard
- [ ] Multiple persona support

### Phase 3 — Voice & Scale (Weeks 7–9)
- [ ] Whisper STT integration
- [ ] TTS output (Edge TTS)
- [ ] Pronunciation feedback
- [ ] React frontend with progress charts
- [ ] Real-world content ingestion (news simplification)
- [ ] Docker deployment
- [ ] Multi-user support

### Phase 4 — Advanced (Weeks 10–12)
- [ ] Adaptive difficulty engine
- [ ] Peer conversation mode (two agents simulating a dialogue for user to follow)
- [ ] Writing exercises with detailed feedback
- [ ] Integration with external content (Netflix subtitles, podcasts)
- [ ] Mobile-responsive PWA
- [ ] Public launch / open-source release

---

## 13. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent orchestration | LangGraph | Proven at scale (Klarna, LinkedIn), checkpointing, state persistence, human-in-the-loop; reduces boilerplate vs. custom |
| Not CrewAI/AutoGen | LangGraph preferred | CrewAI: less control over conversation flow; AutoGen: group chat model doesn't fit 1-on-1 tutoring |
| SQLite over PostgreSQL | Simplicity | Single-user MVP; upgrade later if needed |
| ChromaDB over Pinecone/Weaviate | Embedded, free | No cloud dependency; good enough for <100K vectors |
| Claude as primary LLM | Nuanced language understanding | Better instruction following for persona maintenance; Gemini Flash for speed-critical paths |
| FSRS over SM-2 | State-of-the-art | 20–40% more efficient retention, personalized to user memory patterns, open-source (py-fsrs) |
| YAML scenarios over DB | Human-readable | Easy to contribute new scenarios; version-controllable |
| Silent grammar correction | UX research | Interrupting flow kills conversation confidence |
| Dedicated Evaluator Agent | WikiHowAgent pattern | Separate QA layer outperforms self-assessment; catches false positives, resolves agent conflicts |
| Multi-provider LLM | Cost + quality balance | Claude (quality) + Gemini Flash (speed) + Ollama (privacy); intelligent failover |
---

## 14. Success Metrics

| Metric | Target | How Measured |
|--------|--------|-------------|
| Daily active usage | >15 min/day | Session duration tracking |
| Vocabulary retention | >85% at 30 days | SRS review accuracy |
| Grammar error reduction | 30% fewer errors after 30 days | Error pattern tracking |
| CEFR level advancement | 1 sub-level per 60 days | Assessment agent |
| User satisfaction | >4.5/5 | Post-session rating |
| Conversation naturalness | >80% of turns feel natural | User feedback sampling |

---

## 15. Security & Privacy

- All user data stored locally (SQLite + ChromaDB on user's machine)
- LLM API calls contain no PII beyond conversation text
- Conversation history encrypted at rest (AES-256)
- No telemetry without explicit opt-in
- GDPR-compliant: full data export + deletion on request

---

## 16. Future Extensions

- **Multiplayer mode** — two learners practice together with agent moderation
- **Immersion mode** — all device notifications in target language
- **AR integration** — point camera at objects, get vocabulary in target language
- **Tutor marketplace** — human tutors can review agent-generated reports
- **Company/team plans** — shared vocabulary for domain-specific language (medical, legal)
- **Gamification layer** — optional XP, streaks, leaderboards (configurable off for serious learners)

---

*End of document.*
