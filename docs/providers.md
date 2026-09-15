# LLM providers

Agents never call a vendor SDK directly — they ask
`src.llm.factory.get_provider(tier)` for a provider and call
`await provider.generate(...)`. This document explains the abstraction, how
routing/failover/retry/circuit-breaking work, and how a self-hoster
configures which providers are actually used.

## The abstraction

`src/llm/provider.py`'s `LLMProvider` is the interface every concrete
provider implements: `is_available()` (cheap, no network — usually "is a key
configured") and `async generate(messages, temperature, max_tokens,
json_mode)`. Everything else (`generate_structured`, `stream`,
`count_tokens`, `health`) has a sane default so a minimal provider still
satisfies the full interface.

Concrete providers (`claude.py`, `gemini.py`, `ollama.py`, `openai.py`)
import their vendor SDK **lazily, inside their methods** — a Claude-only
deployment does not need `langchain-google-genai` or an Ollama client
installed at all.

`fake.py`'s `FakeProvider` returns deterministic, synthetic output (no
network) when `POLYGLOT_DETERMINISTIC=1` — this is what the entire test
suite, benchmarks, and evals run against.

## Tiers

Agents ask for a *capability tier*: `"primary"` (quality), `"fast"`
(latency/cost), `"local"` (privacy/offline). `src/llm/router.py` also
resolves task-oriented aliases onto those three (`critical_reasoning →
primary`, `fast_extraction → fast`, `cheap_classification → fast`,
`local_private → local`) so a caller can express *why* it wants a tier;
`resolve_tier()` falls back to `"primary"` for anything unrecognized.

`TIER_PREFERENCE` (`src/llm/factory.py`) maps each capability tier to its
preferred vendor: `primary → claude`, `fast → gemini`, `local → ollama`.

## Routing, retry, and circuit breaking

`get_provider(tier)` returns a `RoutingProvider` wrapping an ordered chain:
the tier's preferred provider first, then the rest in a stable fallback
order (`claude → gemini → ollama`, with `openai` inserted if
`OPENAI_API_KEY` is set).

On `generate()`:

1. Filter to `available_chain()` — providers that report `is_available()`
   **and** whose circuit breaker is not currently open.
2. For the first candidate, retry the *same* provider up to
   `settings.llm_max_retries` times with exponential backoff
   (`settings.llm_retry_base_delay` → `llm_retry_max_delay`) before giving up
   on it. A transient blip is worth retrying in place; a genuinely dead
   provider is not worth retrying forever.
3. If retries are exhausted, record a circuit-breaker failure for that
   provider and fail over to the next candidate.
4. If the whole chain fails, raise `NoProviderAvailableError`.

The **circuit breaker** (`src/llm/reliability.py`'s `CircuitBreaker`) tracks
consecutive failures *per provider name*, not per `RoutingProvider`
instance — because `get_provider()` builds a fresh `RoutingProvider` (and
fresh concrete provider objects) on every call, only state living outside
any one instance can remember "this provider has been failing" across
turns. After `llm_circuit_breaker_failure_threshold` consecutive failures
(default 3), the provider is skipped entirely — not even attempted — for
`llm_circuit_breaker_cooldown_seconds` (default 30s), instead of paying its
failure latency again on every subsequent turn. A single success fully
closes the breaker.

Every attempt (success or failure) is recorded via
`src/llm/telemetry.py` — latency, tokens, an estimated USD cost
(`estimate_cost`, a static per-model price table — an estimate, not a
billing source of truth), and success/error. `src/llm/cost.py` aggregates
those records per session/user/turn.

## Configuring providers as a self-hoster

Set any combination of these in `.env` (see `.env.example`):

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables Claude (primary tier) |
| `GOOGLE_API_KEY` | Enables Gemini (fast tier) |
| `OPENAI_API_KEY` | Enables OpenAI as an extra fallback |
| `OLLAMA_BASE_URL` | Enables local Ollama (local tier); default `http://localhost:11434` |

At least one of a hosted key, `OLLAMA_BASE_URL`, or
`POLYGLOT_DETERMINISTIC=1` must be set — `src.config.validate_settings()`
fails fast at startup otherwise, and `polyglot health` reports the same
check.

**Local-only mode** (`settings.local_only`, or `LOCAL_ONLY=true`): every
hosted provider (`claude`, `gemini`, `openai`) is excluded from every tier's
chain **regardless of which API keys are configured**. If Ollama is also
unavailable, `generate()` raises rather than silently falling back to a
hosted provider — this is what makes "no learning data leaves this machine"
an enforced guarantee instead of a suggestion.

Reliability tuning (all optional, sensible defaults in `.env.example`):
`LLM_MAX_RETRIES`, `LLM_RETRY_BASE_DELAY`, `LLM_RETRY_MAX_DELAY`,
`LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD`,
`LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS`.

## Deterministic mode

`POLYGLOT_DETERMINISTIC=1` (or `true`/`yes`/`on`) makes `get_provider()`
return a single-provider chain of `FakeProvider()` for every tier — no
network, no keys, reproducible output derived only from the input messages.
`tests/conftest.py` sets this before any application module is imported, so
the whole test suite (and `make test`/`make benchmark`/`make eval`) runs
fully offline by default.
