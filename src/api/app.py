"""FastAPI application factory for Polyglot Swarm.

Assembles the API: auth, sessions/chat, review, progress, scenarios, and
profile routes. Multi-user — every request is scoped to the ``user_id``
resolved from its bearer token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api import auth
from src.api.routes import (
    auth_routes,
    chat_routes,
    profile_routes,
    progress_routes,
    review_routes,
    scenario_routes,
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    auth.init_db()
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="Polyglot Swarm API",
        version="0.1.0",
        description="Multi-agent AI language learning — REST API.",
        lifespan=_lifespan,
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(review_routes.router)
    app.include_router(progress_routes.router)
    app.include_router(scenario_routes.router)
    app.include_router(profile_routes.router)

    return app


app = create_app()
