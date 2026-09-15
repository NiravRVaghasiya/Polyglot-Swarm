"""FastAPI application factory for Polyglot Swarm.

Assembles the API: auth, sessions/chat, review, progress, scenarios, and
profile routes. Multi-user — every request is scoped to the ``user_id``
resolved from its bearer token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src import __version__
from src.api import auth
from src.api.routes import (
    auth_routes,
    chat_routes,
    cost_routes,
    learner_routes,
    privacy_routes,
    profile_routes,
    progress_routes,
    review_routes,
    scenario_routes,
    trace_routes,
    voice_routes,
)


def _readiness_checks() -> dict[str, dict[str, Any]]:
    """Run the readiness sub-checks: DB, LLM providers, vector store.

    Distinct from ``/health`` (a pure liveness probe — "is the process up")
    per the plan's rule that a readiness probe verifies the app can actually
    serve traffic, not just that it started. Each sub-check is isolated so one
    failing dependency reports clearly instead of raising through the whole
    endpoint; none of the checks make a real network call to an LLM vendor
    (mirroring :meth:`~src.llm.factory.RoutingProvider.health`), so this is
    safe to poll frequently (e.g. every few seconds from an orchestrator).
    """
    return {
        "database": _check_database(),
        "llm_providers": _check_llm_providers(),
        "vector_store": _check_vector_store(),
    }


def _check_database() -> dict[str, Any]:
    from src.memory.db import get_connection

    try:
        with get_connection() as conn:
            conn.execute("SELECT 1")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        return {"ok": False, "error": str(exc)}


def _check_llm_providers() -> dict[str, Any]:
    from src.llm.factory import get_provider

    try:
        chain_health = {
            tier: get_provider(tier).health()  # no network calls (config check only)
            for tier in ("primary", "fast", "local")
        }
        any_available = any(h["available"] for h in chain_health.values())
        return {"ok": any_available, "tiers": chain_health}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        return {"ok": False, "error": str(exc)}


def _check_vector_store() -> dict[str, Any]:
    from src.memory.vector_store import get_vector_store

    try:
        store = get_vector_store()
        store.count("vocabulary")  # cheap reachability check on one collection
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        # The vector store is an enrichment layer (cultural notes/semantic
        # search), not required for core chat/grammar/vocabulary flows — so
        # unlike the database, its absence degrades rather than fails
        # overall readiness. Still reported so operators can see it's down.
        return {"ok": True, "degraded": True, "error": str(exc)}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from src.config import settings
    from src.memory import model_runs, schema
    from src.observability.logging_config import ensure_configured

    ensure_configured()  # Phase 23: structured/leveled logging from the start
    schema.init_all()  # provision the full schema (migrations) at startup
    if settings.telemetry_enabled:  # Phase 21: configurable telemetry
        model_runs.enable_persistence()  # persist LLM telemetry to model_runs
    auth.init_db()
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Polyglot Swarm API",
        version=__version__,
        description="Multi-agent AI language learning — REST API.",
        lifespan=_lifespan,
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["health"])
    def ready() -> JSONResponse:
        checks = _readiness_checks()
        overall_ok = all(c["ok"] for c in checks.values())
        status_code = 200 if overall_ok else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ok" if overall_ok else "unavailable", "checks": checks},
        )

    app.include_router(auth_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(review_routes.router)
    app.include_router(progress_routes.router)
    app.include_router(scenario_routes.router)
    app.include_router(profile_routes.router)
    app.include_router(learner_routes.router)
    app.include_router(trace_routes.router)
    app.include_router(privacy_routes.router)
    app.include_router(cost_routes.router)
    app.include_router(voice_routes.router)

    return app


app = create_app()
