"""Concrete providers for real-model evaluation, and an availability probe.

The app normally reaches models through :func:`src.llm.factory.get_provider`,
which fails over between providers and resolves to a fake provider in
deterministic mode. Both would corrupt an evaluation (a result labeled
"claude" could have come from Gemini, or from no model at all), so the
evaluation builds **one concrete provider per spec** and never routes.

The deterministic fake provider is available only when the caller explicitly
allows synthetic runs; such runs are labeled ``synthetic`` in every artifact
and report.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from src.config import settings
from src.llm.provider import LLMProvider, Message
from src.llm.reliability import _http_status

#: Provider names the runner can build. ``fake`` is synthetic-only.
REAL_PROVIDERS = ("claude", "openai", "gemini", "ollama")
SYNTHETIC_PROVIDERS = ("fake",)


class SyntheticProviderError(ValueError):
    """A synthetic provider was requested without allowing synthetic runs."""


@dataclass(frozen=True)
class ProviderSpec:
    """``<provider>:<model>``; the model defaults to the app's configured one."""

    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def synthetic(self) -> bool:
        return self.provider in SYNTHETIC_PROVIDERS


def default_model(provider: str) -> str:
    from src.llm.ollama import _strip_provider_prefix
    from src.llm.openai import _DEFAULT_MODEL

    return {
        "claude": settings.llm_primary,
        "gemini": settings.llm_fast,
        "openai": _DEFAULT_MODEL,
        "ollama": _strip_provider_prefix(settings.llm_local),
        "fake": "fake-deterministic",
    }[provider]


def parse_spec(text: str) -> ProviderSpec:
    """Parse ``provider[:model]`` (the model may itself contain ``:``)."""
    provider, _, model = text.strip().partition(":")
    provider = provider.lower()
    if provider not in REAL_PROVIDERS + SYNTHETIC_PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of {REAL_PROVIDERS}")
    return ProviderSpec(provider, model or default_model(provider))


def build_provider(spec: ProviderSpec, *, allow_synthetic: bool = False) -> LLMProvider:
    """Construct exactly the requested provider/model — no routing, no failover."""
    if spec.synthetic and not allow_synthetic:
        raise SyntheticProviderError(
            f"{spec.key} is synthetic; pass allow_synthetic to run it "
            "(results are labeled synthetic)"
        )
    if spec.provider == "claude":
        from src.llm.claude import ClaudeProvider

        return ClaudeProvider(model=spec.model)
    if spec.provider == "openai":
        from src.llm.openai import OpenAIProvider

        return OpenAIProvider(model=spec.model)
    if spec.provider == "gemini":
        from src.llm.gemini import GeminiProvider

        return GeminiProvider(model=spec.model)
    if spec.provider == "ollama":
        from src.llm.ollama import OllamaProvider

        return OllamaProvider(model=spec.model)
    from src.llm.fake import FakeProvider

    return FakeProvider()


# Probe outcomes. Only "available" providers are evaluated; the others are
# recorded as unavailable, which is different from a failed evaluation.
AVAILABLE = "available"
NOT_CONFIGURED = "not_configured"
UNREACHABLE = "unreachable"
AUTH_FAILED = "auth_failed"
MODEL_NOT_FOUND = "model_not_found"
SDK_MISSING = "sdk_missing"
TIMEOUT = "timeout"
ERROR = "error"


def classify_error(exc: BaseException) -> str:
    """Map a provider exception to a stable error category."""
    if isinstance(exc, ImportError):
        return SDK_MISSING
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return TIMEOUT
    status = _http_status(exc)
    text = f"{type(exc).__name__} {exc}".lower()
    if status in (401, 403) or any(
        k in text
        for k in (
            "authentication",
            "api key",
            "api_key",
            "api-key",
            "unauthorized",
            "permission",
            "error code: 401",
            "error code: 403",
        )
    ):
        return AUTH_FAILED
    if status == 404 or ("model" in text and ("not found" in text or "pull" in text)):
        return MODEL_NOT_FOUND
    if any(
        k in text
        for k in ("connect", "connection refused", "name resolution", "getaddrinfo", "unreachable")
    ):
        return UNREACHABLE
    if "timeout" in text or "timed out" in text:
        return TIMEOUT
    return ERROR


@dataclass
class ProbeResult:
    spec: ProviderSpec
    status: str
    detail: str = ""
    latency_ms: float = 0.0
    reported_model: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.spec.provider,
            "model": self.spec.model,
            "status": self.status,
            "detail": self.detail[:500],
            "latency_ms": round(self.latency_ms, 1),
            "reported_model": self.reported_model,
            "synthetic": self.spec.synthetic,
        }


async def probe(
    spec: ProviderSpec, *, timeout_s: float = 60.0, allow_synthetic: bool = False
) -> ProbeResult:
    """Make one tiny real call to find out whether a provider can be evaluated."""
    try:
        provider = build_provider(spec, allow_synthetic=allow_synthetic)
    except SyntheticProviderError as exc:
        return ProbeResult(spec, ERROR, str(exc))
    if not provider.is_available():
        return ProbeResult(spec, NOT_CONFIGURED, "no API key / base URL configured")
    start = time.perf_counter()
    try:
        completion = await asyncio.wait_for(
            provider.generate_detailed(
                [Message("user", "Reply with the single word OK.")],
                temperature=0.0,
                max_tokens=5,
            ),
            timeout=timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - classify every failure
        return ProbeResult(
            spec,
            classify_error(exc),
            f"{type(exc).__name__}: {exc}",
            (time.perf_counter() - start) * 1000,
        )
    return ProbeResult(
        spec,
        AVAILABLE,
        latency_ms=(time.perf_counter() - start) * 1000,
        reported_model=completion.reported_model,
    )
