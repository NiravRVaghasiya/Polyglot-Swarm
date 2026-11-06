"""Live checks that an LLM backend can actually serve requests.

:meth:`~src.llm.provider.LLMProvider.health` only inspects configuration (a key
is set, a base URL is set) and never touches the network, which keeps the API's
``/ready`` probe cheap. That is not enough for setup: Ollama can be configured
but not running, or running without the configured model pulled, and the
first conversation turn then fails with a canned fallback reply. These checks
ask a local Ollama which models it has, so ``polyglot health`` and ``polyglot
chat`` can say exactly what to fix. Hosted API keys are reported as set but
are not verified, since that would cost a billed request.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

import httpx

from src.config import Settings, settings
from src.llm.fake import is_deterministic
from src.llm.ollama import _strip_provider_prefix


@dataclass(frozen=True)
class BackendCheck:
    """The outcome of checking one LLM backend."""

    name: str
    ok: bool
    detail: str
    fix: str = ""


def check_backends(s: Settings | None = None, *, timeout: float = 3.0) -> list[BackendCheck]:
    """Check every configured LLM backend; at least one ``ok`` means chat works."""
    s = s or settings
    if is_deterministic():
        return [
            BackendCheck(
                "deterministic",
                True,
                "offline demo mode: replies are canned and no model is called",
            )
        ]

    checks: list[BackendCheck] = []
    if not s.local_only:
        for name, key, var in (
            ("claude", s.anthropic_api_key, "ANTHROPIC_API_KEY"),
            ("gemini", s.google_api_key, "GOOGLE_API_KEY"),
            ("openai", s.openai_api_key, "OPENAI_API_KEY"),
        ):
            if key:
                checks.append(BackendCheck(name, True, f"{var} is set (not verified)"))
    if s.ollama_base_url:
        checks.append(_check_ollama(s, timeout))
    return checks


def has_usable_backend(checks: list[BackendCheck]) -> bool:
    return any(c.ok for c in checks)


def _check_ollama(s: Settings, timeout: float) -> BackendCheck:
    model = _strip_provider_prefix(s.llm_local)
    url = s.ollama_base_url.rstrip("/")
    # Only whether it is installed matters here; importing it would pull in all
    # of langchain just to print a health line.
    if importlib.util.find_spec("langchain_ollama") is None:
        return BackendCheck(
            "ollama",
            False,
            "the langchain-ollama package is not installed",
            'Reinstall the project: pip install -e ".[dev]"',
        )

    try:
        resp = httpx.get(f"{url}/api/tags", timeout=timeout)
        resp.raise_for_status()
        installed = {m.get("name", "") for m in resp.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        return BackendCheck(
            "ollama",
            False,
            f"no Ollama server answering at {url}",
            "Install Ollama from https://ollama.com and start it, or use an API key "
            "or offline mode instead.",
        )

    wanted = model if ":" in model else f"{model}:latest"
    if wanted in installed:
        return BackendCheck("ollama", True, f"model {model} is ready at {url}")

    fix = f"Run: ollama pull {model}"
    family = model.split(":", 1)[0]
    alternatives = sorted(name for name in installed if name.split(":", 1)[0] == family)
    if alternatives:
        fix += f"  (or set LLM_LOCAL=ollama/{alternatives[0]} in .env to use the copy you have)"
    return BackendCheck("ollama", False, f"Ollama is running but model {model} is not pulled", fix)
