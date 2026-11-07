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
   provider is not worth retrying forever. Errors that cannot succeed on a
   retry (`reliability.is_retryable`: a missing SDK package, or a 4xx such as
   a bad key or an Ollama model that was never pulled) skip the retries.
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
| `ANTHROPIC_API_KEY` | Enables Claude (primary tier, model `LLM_PRIMARY`, default `claude-sonnet-5-5`) |
| `GOOGLE_API_KEY` | Enables Gemini (fast tier, model `LLM_FAST`, default `gemini-3.6-flash`) |
| `OPENAI_API_KEY` | Enables OpenAI as an extra fallback (model `LLM_OPENAI`, default `gpt-4o-mini`) |
| `OLLAMA_BASE_URL` | Enables local Ollama (local tier, model `LLM_LOCAL`, default `ollama/llama3.1:8b`); default `http://localhost:11434` |
| `OLLAMA_NUM_CTX` | Context window requested from Ollama (default `8192`). Without a cap Ollama may reserve the model's full context — 128k tokens for Llama 3.1, a ~16 GB KV cache — and fail with out-of-memory. |

For Ollama, pull the configured model once (`ollama pull llama3.1:8b`); a
model that isn't pulled answers 404 on every call.

The Claude provider never sends `temperature`: current Claude models reject
non-default sampling parameters, and API version `2026-10-21` rejects them on
every model.

`OLLAMA_BASE_URL` has a non-empty default, so configuration alone can't tell
whether a backend works. `polyglot health` (`src/llm/preflight.py`) asks
Ollama which models it actually has and reports hosted keys as set (not
verified, since that would cost a request); it exits non-zero and prints a
`fix:` line when nothing can answer. `polyglot chat` runs the same check
before starting, and `python -m src.main` warns at launch.

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
