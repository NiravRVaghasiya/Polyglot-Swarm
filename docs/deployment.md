# Deployment

> **Staging and production** use [`docker-compose.prod.yml`](../docker-compose.prod.yml)
> with `APP_ENV=staging|production`, which refuses to start on unsafe
> settings. Start from [`.env.production.example`](../.env.production.example)
> and follow the [operations runbook](production/operations-runbook.md):
> deploy, rollback, backups and restore, alerts and incidents. The other
> production documents:
>
> - [readiness audit and risk register](production/readiness-audit.md);
> - [security and privacy review](production/security-privacy-review.md);
> - [service objectives](production/service-objectives.md);
> - [performance report](production/performance-report.md).
>
> The rest of this page covers local and self-hosted development setups.

## Running locally without Docker

The README's [Quick start](../README.md#quick-start) has the full
step-by-step setup for Windows, macOS and Linux, including choosing an LLM
backend and a troubleshooting table. In short:

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: py -3.12 -m venv .venv; .venv\Scripts\Activate.ps1
python -m pip install -e ".[all]"   # or ".[dev]" without the voice extra
cp .env.example .env                # then choose option A, B or C inside it
polyglot health                     # checks the backend actually answers

python -m src.main                  # Gradio chat + voice UI, port 7860
uvicorn src.api.app:app --reload --port 8000   # or the REST API
```

`polyglot health` asks Ollama which models it has, reports hosted keys as set,
and exits non-zero when no backend can answer — useful in CI or a deploy
script as a pre-flight check.

## Docker Compose

```bash
cp .env.example .env    # choose option A, B or C inside it first
docker compose up --build                       # API (:8000) + Gradio UI (:7860)
docker compose --profile web up --build         # also the React dashboard (:3000)
docker compose --profile local-llm up --build   # also an Ollama container (:11434)
docker compose exec ollama ollama pull llama3.1:8b   # once, with local-llm running
```

`docker-compose.yml` builds one image (`Dockerfile`) and runs it twice with
different commands: the `api` service runs
`uvicorn src.api.app:app --host 0.0.0.0 --port 8000`; the `ui` service runs
`python -m src.main` (Gradio). Both share a named volume (`polyglot-data`,
mounted at `/data`) so the API and UI see the same SQLite database and
ChromaDB directory. The `ui` service waits on the API's Docker healthcheck
(`GET /health`) before starting, and sets `GRADIO_SERVER_NAME=0.0.0.0` so the
UI is reachable from outside its container.

Every port is published on `127.0.0.1` only, so the stack is reachable from
this machine but not from the network: the Gradio UI and Ollama have no
authentication. To serve other machines, use `docker-compose.prod.yml`
(below) behind a TLS-terminating reverse proxy.

Both services override `OLLAMA_BASE_URL` to `http://ollama:11434` (the
`local-llm` container), because `localhost` inside a container is the
container itself. To use an Ollama running on the host instead, change it to
`http://host.docker.internal:11434` at the top of `docker-compose.yml`.

The `web` service (`profiles: ["web"]`) runs the React dashboard from a
`node:24-alpine` image, installing and building on first start.

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
- **Server**: `API_HOST`, `API_PORT`, `GRADIO_SERVER_PORT`, `CORS_ORIGINS`
  (browser origins allowed to call the API; defaults to the React dev server).
- **Security**: `TOKEN_TTL_HOURS`, `TELEMETRY_ENABLED`, `MIN_PASSWORD_LENGTH`,
  `METRICS_TOKEN`, `GRADIO_AUTH`.
- **Production controls** (ADR-0035):
  - `APP_ENV`, `API_DOCS_ENABLED`;
  - `MAX_REQUEST_BYTES`, `USER_RATE_LIMIT_PER_MINUTE`;
  - `LLM_TIMEOUT_SECONDS`, `LLM_MAX_CALLS_PER_TURN`;
  - `LLM_USER_DAILY_BUDGET_USD`, `LLM_USER_DAILY_CALLS`,
    `LLM_GLOBAL_DAILY_BUDGET_USD`;
  - `MAX_ACTIVE_SESSIONS_PER_USER`, `SESSION_IDLE_FINALIZE_HOURS`;
  - `BACKUP_RETENTION_COUNT`, `MAINTENANCE_INTERVAL_SECONDS`.

  Run `polyglot ops config-check` to validate.
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

`frontend/react_app/` is a separate Next.js app (Compose runs it only with
`--profile web`). Run it independently with Node.js 22+:

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
`npm run typecheck` and `npm test`.

## CI and local quality gates

`make check` (`lint format-check typecheck test`) is the single local gate;
CI runs the same targets via `make ci`. See [`CONTRIBUTING.md`](../CONTRIBUTING.md)
for the full developer workflow, including Windows notes (`make` is not
installed by default — use WSL/Git Bash, install GNU Make, or run each
recipe's underlying command directly).
