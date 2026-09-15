# Deployment

## Running locally without Docker

```bash
git clone https://github.com/NiravRVaghasiya/Polyglot-Swarm.git
cd Polyglot-Swarm
pip install -e ".[all]"          # or ".[dev]" without the voice extra
cp .env.example .env              # set at least one LLM key, or OLLAMA_BASE_URL,
                                   # or POLYGLOT_DETERMINISTIC=1 for offline mode

python -m src.main                 # Gradio chat + voice UI, port 7860
# or
uvicorn src.api.app:app --reload --port 8000   # the REST API
```

`polyglot health` (installed as a console script via `pyproject.toml`'s
`[project.scripts]`) reports configuration and provider health, and exits
non-zero on a real misconfiguration — useful in CI or a deploy script as a
pre-flight check.

## Docker Compose

```bash
cp .env.example .env    # set your LLM key(s) first
docker compose up                       # API (:8000) + Gradio UI (:7860)
docker compose --profile local-llm up   # also start an Ollama container (:11434)
```

`docker-compose.yml` builds one image (`Dockerfile`) and runs it twice with
different commands: the `api` service runs
`uvicorn src.api.app:app --host 0.0.0.0 --port 8000`; the `ui` service runs
`python -m src.main` (Gradio). Both share a named volume (`polyglot-data`,
mounted at `/data`) so the API and UI see the same SQLite database and
ChromaDB directory. The `ui` service waits on the API's Docker healthcheck
(`GET /health`) before starting.

The `ollama` service is opt-in (`profiles: ["local-llm"]`) — it is not
started by a plain `docker compose up`, since most self-hosters either use a
hosted key or already run Ollama outside Compose.

**Voice extra**: the Dockerfile's base image installs runtime deps only
(`pip install .`). To enable STT/TTS/LiveKit inside the container, change
that line to `pip install .[voice]` (or `.[all]`) and rebuild.

## Configuration reference

All settings are environment variables (loaded via `.env`,
`pydantic-settings`) — see `.env.example` for the full list with defaults.
Notable groups:

- **LLM providers**: `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`,
  `OPENAI_API_KEY`, `OLLAMA_BASE_URL`, `LOCAL_ONLY`. See
  [`providers.md`](providers.md).
- **Reliability**: `LLM_MAX_RETRIES`, `LLM_RETRY_BASE_DELAY`,
  `LLM_RETRY_MAX_DELAY`, `LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD`,
  `LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS`.
- **Logging**: `LOG_LEVEL` (default `INFO`), `LOG_FORMAT` (`text` for local
  dev, `json` for a log aggregator).
- **Storage**: `DATA_DIR`, `DB_PATH`, `CHROMA_PATH`, `PROFILES_DIR`.
- **Server**: `API_HOST`, `API_PORT`, `GRADIO_SERVER_PORT`.
- **Security**: `TOKEN_TTL_HOURS`, `TELEMETRY_ENABLED`.
- **Voice** (optional): `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
  `LIVEKIT_API_SECRET`.

## Health and readiness

- `GET /health` — pure liveness: "is the process up." No dependency checks;
  used by the Docker healthcheck.
- `GET /ready` (Phase 23) — checks the database (`SELECT 1`), the LLM
  provider chain (`get_provider(tier).health()` per tier — configuration
  only, no network calls, so safe to poll frequently), and the vector store
  (a cheap collection `count()`). Returns HTTP 503 if the database or every
  LLM tier is unavailable; a vector-store failure is reported as `degraded`
  but does not fail overall readiness, since it's an enrichment layer, not
  required for core chat/grammar/vocabulary flows.

Point an orchestrator's readiness probe at `/ready`, not `/health` — a
process that's "up" but has no working LLM provider or a broken database
connection should not receive traffic.

## The React frontend

`frontend/react_app/` is a separate Next.js app, not built or served by the
Dockerfile/Compose stack. Run it independently:

```bash
cd frontend/react_app
npm install
npm run dev
```

It talks to the FastAPI backend via `src/lib/api.ts` using the caller's
bearer token; point it at your API's base URL (`NEXT_PUBLIC_API_URL`, default
`http://localhost:8000`).

The web app includes:

- **Voice** — a mic button in the chat panel records audio, sends it to
  `POST /api/v1/voice/transcribe` (local Whisper) and, when "Speak replies
  aloud" is enabled, plays synthesized replies from `POST /api/v1/voice/speak`
  (Edge TTS). Both endpoints degrade to 503 if the server's `voice` extra
  isn't installed, and the UI falls back to text-only.
- **PWA / mobile** — a viewport meta, an installable `manifest.json` with an
  icon, and a service worker (`public/sw.js`) that caches the app shell for
  offline load. API traffic is never cached (it's authenticated and must be
  fresh).
- **Onboarding** — a first-run wizard captures the learner's language and
  goal and writes them to their profile, shown until a goal is set.

Frontend quality gates (type-check + vitest) run in CI; run them locally with
`npm run lint`, `npx tsc --noEmit`, and `npm test`.

## CI and local quality gates

`make check` (`lint format-check typecheck test`) is the single local gate;
CI runs the same targets via `make ci`. See [`CONTRIBUTING.md`](../CONTRIBUTING.md)
for the full developer workflow, including Windows notes (`make` is not
installed by default — use WSL/Git Bash, install GNU Make, or run each
recipe's underlying command directly).
