"""Application configuration loaded from environment variables.

Beyond loading, this module *validates* configuration so a misconfigured
deployment fails fast with a clear message rather than only erroring on the
first LLM call. The rule: at least one usable LLM backend must be reachable —
a hosted provider key, a local Ollama base URL, or deterministic mode.
"""

from __future__ import annotations

import os

from pydantic import model_validator
from pydantic_settings import BaseSettings


def _deterministic_mode_active() -> bool:
    """Whether deterministic mode is on (mirrors src.llm.fake.is_deterministic).

    Duplicated here to avoid importing the LLM package at config-load time.
    """
    return os.getenv("POLYGLOT_DETERMINISTIC", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class Settings(BaseSettings):
    """Global application settings."""

    # LLM providers
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    #: Context window requested from Ollama. Without it, Ollama may reserve the
    #: model's full context (128k tokens for Llama 3.1, a ~16 GB KV cache) and
    #: fail with out-of-memory on ordinary machines. Prompts here are small.
    ollama_num_ctx: int = 8192

    #: Offline demo/test mode: every LLM call goes to a deterministic fake
    #: provider, so no key or local model is needed. Usually set as the
    #: POLYGLOT_DETERMINISTIC environment variable; settable in .env too.
    polyglot_deterministic: bool = False

    # LLM routing
    llm_primary: str = "claude-sonnet-5-5"
    llm_fast: str = "gemini-3.6-flash"
    llm_local: str = "ollama/llama3.1:8b"
    #: OpenAI has no tier of its own; it joins the routing chain as an extra
    #: fallback when ``OPENAI_API_KEY`` is set.
    llm_openai: str = "gpt-4o-mini"

    # Language
    default_language: str = "Spanish"

    # FSRS
    fsrs_desired_retention: float = 0.9

    # Storage
    data_dir: str = "./data"
    db_path: str = "./data/polyglot.db"
    chroma_path: str = "./data/chroma"
    profiles_dir: str = "./data/user_profiles"

    # Security (Phase 21)
    #: Bearer-token lifetime. Tokens expire and stop resolving after this long,
    #: even if never explicitly logged out.
    token_ttl_hours: int = 24 * 30  # 30 days

    #: Whether LLM-call telemetry (latency/tokens/cost) is persisted to the
    #: model_runs table. The in-memory ring buffer (src.llm.telemetry) still
    #: records regardless — this only gates the durable *sink*, so disabling
    #: it stops call metadata from accumulating on disk across restarts.
    telemetry_enabled: bool = True

    # Logging (Phase 23)
    #: Root log level name (e.g. "DEBUG", "INFO", "WARNING").
    log_level: str = "INFO"
    #: "json" for structured, one-line-per-record JSON logs (production/
    #: log-aggregator friendly); "text" for the traditional human-readable
    #: format (nicer for local development in a terminal).
    log_format: str = "text"

    # Reliability (Phase 23)
    #: Bounded retries of the *same* provider before failing over to the next
    #: one in the chain. 0 preserves the original behavior (one attempt per
    #: provider, then immediate failover).
    llm_max_retries: int = 2
    #: Exponential backoff base/cap (seconds) between retries of one provider.
    llm_retry_base_delay: float = 0.2
    llm_retry_max_delay: float = 2.0
    #: Circuit breaker: after this many *consecutive* failures a provider is
    #: skipped (not even attempted) for `llm_circuit_breaker_cooldown_seconds`,
    #: instead of paying its failure latency again on every subsequent turn.
    llm_circuit_breaker_failure_threshold: int = 3
    llm_circuit_breaker_cooldown_seconds: float = 30.0

    #: Local-only mode: when true, the LLM provider factory refuses to build
    #: a chain that could reach a hosted provider (Claude/Gemini/OpenAI),
    #: regardless of which API keys are configured — only Ollama (local) and
    #: the deterministic fake provider are eligible. This is what makes "run
    #: the full stack without sending learning data to third parties" an
    #: enforced guarantee rather than just "don't set the keys".
    local_only: bool = False

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    gradio_server_port: int = 7860
    #: Comma-separated browser origins allowed to call the API (CORS). The
    #: React app is served from its own origin, so without this the browser
    #: blocks its requests. Empty disables CORS entirely.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Production controls (Phase 5, ADR-0035) ------------------------------
    #: ``development`` | ``staging`` | ``production``. Staging and production
    #: fail fast on unsafe configuration (see :func:`validate_settings`).
    app_env: str = "development"
    #: Serve ``/docs`` and ``/openapi.json``. Must be off in production.
    api_docs_enabled: bool = True
    #: Largest accepted request body (bytes). Base64 audio of the 10 MB
    #: upload limit is about 13.4 MB, so 16 MB leaves room for the JSON.
    max_request_bytes: int = 16 * 1024 * 1024
    #: Per-user requests per minute on learning endpoints that do work
    #: (chat, assessment, review submission). 0 disables.
    user_rate_limit_per_minute: int = 60
    #: Seconds before one LLM attempt is abandoned (then retried / failed over).
    llm_timeout_seconds: float = 45.0
    #: LLM calls allowed while handling one turn (a runaway-loop guard).
    llm_max_calls_per_turn: int = 16
    #: Per-user daily LLM spend (estimated USD) and call caps. 0 disables.
    llm_user_daily_budget_usd: float = 2.0
    llm_user_daily_calls: int = 1500
    #: Whole-deployment daily LLM spend cap (estimated USD). 0 disables.
    llm_global_daily_budget_usd: float = 0.0
    #: In-flight chat sessions per user; the oldest idle one is finalized.
    max_active_sessions_per_user: int = 5
    #: Idle sessions older than this are finalized by maintenance (hours).
    session_idle_finalize_hours: float = 6.0
    #: Minimum length for new passwords.
    min_password_length: int = 8
    #: Bearer token required to read ``/metrics``. Empty: only outside
    #: staging/production (where it is required).
    metrics_token: str = ""
    #: Gradio UI credentials as ``user:password``. Required to start the
    #: Gradio UI in staging/production.
    gradio_auth: str = ""
    #: Backup sets kept by ``polyglot ops backup`` (oldest pruned first).
    backup_retention_count: int = 14
    #: Seconds between in-process maintenance runs (0 disables the loop).
    maintenance_interval_seconds: float = 900.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_production_like(self) -> bool:
        """Staging and production share the strict rules."""
        return self.app_env.strip().lower() in {"staging", "production"}

    def has_hosted_provider(self) -> bool:
        """Whether any hosted-provider API key is configured."""
        return bool(self.anthropic_api_key or self.google_api_key or self.openai_api_key)

    def has_local_provider(self) -> bool:
        """Whether a local Ollama endpoint is configured."""
        return bool(self.ollama_base_url)

    def cors_origin_list(self) -> list[str]:
        """The configured CORS origins, parsed from the comma-separated setting."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def configured_backends(self) -> list[str]:
        """Names of the LLM backends this configuration can reach."""
        backends: list[str] = []
        if self.anthropic_api_key:
            backends.append("claude")
        if self.google_api_key:
            backends.append("gemini")
        if self.openai_api_key:
            backends.append("openai")
        if self.ollama_base_url:
            backends.append("ollama")
        if _deterministic_mode_active():
            backends.append("deterministic")
        return backends

    @model_validator(mode="after")
    def _validate_retention(self) -> Settings:
        if not 0.0 < self.fsrs_desired_retention <= 1.0:
            raise ValueError(
                "FSRS_DESIRED_RETENTION must be in the interval (0.0, 1.0], "
                f"got {self.fsrs_desired_retention!r}."
            )
        return self


#: Settings field holding each provider's model id.
_MODEL_FIELDS = {
    "claude": "llm_primary",
    "gemini": "llm_fast",
    "openai": "llm_openai",
    "ollama": "llm_local",
}


def default_model_ids() -> dict[str, str]:
    """Each provider's model id as defined in code, ignoring the environment.

    ``settings`` reflects the environment and ``.env``, which differ per
    machine; these defaults are what a deployment runs unless its operator
    overrides them, so they are the models an evaluation should measure.
    """
    fields = Settings.model_fields
    return {provider: str(fields[name].default) for provider, name in _MODEL_FIELDS.items()}


def validate_settings(s: Settings, *, strict: bool = False) -> list[str]:
    """Return a list of human-readable configuration problems.

    A "problem" means the app cannot function correctly. When ``strict`` is set,
    the first problem is raised as ``RuntimeError`` (used by the health command
    and startup checks); otherwise the caller decides what to do with the list.

    In deterministic mode all provider checks are satisfied by definition.
    """
    problems: list[str] = []

    if not _deterministic_mode_active():
        if not (s.has_hosted_provider() or s.has_local_provider()):
            problems.append(
                "No LLM backend configured. Set at least one of "
                "ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY, or "
                "OLLAMA_BASE_URL for local mode (or POLYGLOT_DETERMINISTIC=1 "
                "for offline/deterministic mode)."
            )

    if s.app_env.strip().lower() not in {"development", "staging", "production"}:
        problems.append(f"APP_ENV must be development, staging or production, got {s.app_env!r}.")
    if s.is_production_like:
        problems.extend(_production_problems(s))
    if strict and problems:
        raise RuntimeError("; ".join(problems))
    return problems


def _production_problems(s: Settings) -> list[str]:
    """Unsafe settings for staging/production (each one blocks startup)."""
    problems: list[str] = []
    if _deterministic_mode_active():
        problems.append("POLYGLOT_DETERMINISTIC must be off in staging/production.")
    origins = s.cors_origin_list()
    if not origins or any(
        not o.startswith("https://") or "localhost" in o or "127.0.0.1" in o for o in origins
    ):
        problems.append("CORS_ORIGINS must list only https:// origins (no localhost).")
    if s.api_docs_enabled:
        problems.append("API_DOCS_ENABLED must be false in staging/production.")
    if s.log_format != "json":
        problems.append("LOG_FORMAT must be json in staging/production.")
    if len(s.metrics_token) < 24:
        problems.append("METRICS_TOKEN must be set (at least 24 characters).")
    if s.llm_user_daily_budget_usd <= 0 or s.llm_global_daily_budget_usd <= 0:
        problems.append(
            "LLM_USER_DAILY_BUDGET_USD and LLM_GLOBAL_DAILY_BUDGET_USD must be positive."
        )
    if s.user_rate_limit_per_minute <= 0:
        problems.append("USER_RATE_LIMIT_PER_MINUTE must be positive.")
    if not s.telemetry_enabled:
        problems.append("TELEMETRY_ENABLED must be true (cost and budget tracking need it).")
    return problems


def export_deterministic_mode(s: Settings) -> None:
    """Make a deterministic-mode flag set only in .env visible process-wide.

    Deterministic mode is checked via the process environment
    (:func:`src.llm.fake.is_deterministic`), which never sees values that
    pydantic-settings read from .env. A value already in the environment wins,
    so an explicit shell setting stays authoritative.
    """
    if s.polyglot_deterministic and "POLYGLOT_DETERMINISTIC" not in os.environ:
        os.environ["POLYGLOT_DETERMINISTIC"] = "1"


settings = Settings()
export_deterministic_mode(settings)
