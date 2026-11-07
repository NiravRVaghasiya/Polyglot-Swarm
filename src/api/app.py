"""FastAPI application factory for Polyglot Swarm.

Assembles the API: auth, sessions/chat, review, progress, scenarios, and
profile routes. Multi-user — every request is scoped to the ``user_id``
resolved from its bearer token.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from src import __version__
from src.api import auth
from src.api.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from src.api.routes import (
    assessment_routes,
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

logger = logging.getLogger("polyglot.api")


def _failed(check: str, exc: Exception) -> dict[str, Any]:
    """A failed sub-check: logged in full, reported by exception class only."""
    logger.error("readiness check %s failed: %s", check, exc)
    return {"ok": False, "error": type(exc).__name__}


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
        from src.memory import schema

        with get_connection() as conn:
            conn.execute("SELECT 1")
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != schema.SCHEMA_VERSION:
            return {"ok": False, "error": "schema_version_mismatch", "schema_version": version}
        return {"ok": True, "schema_version": version}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        return _failed("database", exc)


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
        return _failed("llm_providers", exc)


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
        logger.warning("vector store unavailable: %s", exc)
        return {"ok": True, "degraded": True, "error": type(exc).__name__}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from src.config import settings, validate_settings
    from src.memory import model_runs, schema
    from src.observability.logging_config import ensure_configured
    from src.ops.maintenance import maintenance_loop

    ensure_configured()  # Phase 23: structured/leveled logging from the start
    # Staging/production refuse to start on unsafe configuration (ADR-0035).
    validate_settings(settings, strict=settings.is_production_like)
    schema.init_all()  # provision the full schema (migrations) at startup
    if settings.telemetry_enabled:  # Phase 21: configurable telemetry
        model_runs.enable_persistence()  # persist LLM telemetry to model_runs
    auth.init_db()
    task = (
        asyncio.create_task(maintenance_loop())
        if settings.maintenance_interval_seconds > 0
        else None
    )
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    from src.config import settings

    docs = settings.api_docs_enabled
    app = FastAPI(
        title="Polyglot Swarm API",
        version=__version__,
        description="Multi-agent AI language learning — REST API.",
        lifespan=_lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    origins = settings.cors_origin_list()
    if origins:
        # Auth is a bearer header, not cookies, so credentials stay disallowed.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Retry-After"],
        )
    # Added last = outermost: every response (including CORS and 413s) gets a
    # request id, an access-log line and metrics.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production_like)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception(
            "unhandled error on %s %s",
            request.method,
            request.url.path,
            extra={"request_id": request_id or "-"},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "internal error", "request_id": request_id},
            headers={"x-request-id": request_id} if request_id else None,
        )

    @app.get("/metrics", tags=["health"], include_in_schema=False)
    def metrics_endpoint(request: Request) -> PlainTextResponse:
        from src.observability import metrics

        token = settings.metrics_token
        if token:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return PlainTextResponse("unauthorized", status_code=401)
        elif settings.is_production_like:  # pragma: no cover - startup already refuses this
            return PlainTextResponse("metrics disabled", status_code=404)
        return PlainTextResponse(
            metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
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
    app.include_router(assessment_routes.router)

    return app


app = create_app()
