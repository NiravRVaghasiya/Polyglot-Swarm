"""Polyglot Swarm — Gradio UI launcher.

Run with: python -m src.main

Checks that an LLM backend answers, then launches the Gradio chat + voice UI
(:mod:`frontend.gradio_app`) on ``GRADIO_SERVER_PORT``. In staging/production
the UI refuses to start without ``GRADIO_AUTH`` (see :func:`gradio_auth`).
"""

from __future__ import annotations

from typing import Any

from src.config import settings


def gradio_auth(s: Any) -> tuple[str, str] | None:
    """Credentials for the Gradio UI (ADR-0035, R5).

    The UI has no accounts of its own and spends the operator's LLM budget,
    so staging/production refuse to start it without ``GRADIO_AUTH``
    (``user:password``).
    """
    user, sep, password = s.gradio_auth.partition(":")
    if sep and user and len(password) >= s.min_password_length:
        return (user, password)
    if s.is_production_like:
        raise SystemExit(
            "GRADIO_AUTH (user:password, password >= MIN_PASSWORD_LENGTH) is required "
            "to run the Gradio UI in staging/production."
        )
    return None


def main() -> None:
    """Warn if no LLM backend works, then launch the Gradio UI."""
    from src.llm.preflight import check_backends, has_usable_backend

    # The UI still starts, but every reply would be a canned fallback, so say
    # why up front.
    checks = check_backends()
    if not has_usable_backend(checks):
        print("WARNING: no working LLM backend - replies will be canned fallbacks.")
        for check in checks:
            print(f"  {check.name}: {check.detail}" + (f" (fix: {check.fix})" if check.fix else ""))
        print("Run `polyglot health` for setup steps.")

    from frontend.gradio_app import build_ui

    build_ui().launch(server_port=settings.gradio_server_port, auth=gradio_auth(settings))


if __name__ == "__main__":
    main()
