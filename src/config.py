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

    # LLM routing
    llm_primary: str = "claude-sonnet-4-20250514"
    llm_fast: str = "gemini-2.0-flash"
    llm_local: str = "ollama/llama3.1:8b"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def has_hosted_provider(self) -> bool:
        """Whether any hosted-provider API key is configured."""
        return bool(self.anthropic_api_key or self.google_api_key or self.openai_api_key)

    def has_local_provider(self) -> bool:
        """Whether a local Ollama endpoint is configured."""
        return bool(self.ollama_base_url)

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

    if strict and problems:
        raise RuntimeError("; ".join(problems))
    return problems


settings = Settings()
