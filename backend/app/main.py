"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import runtime
from app.api import health, ws
from app.config import Settings, load_settings, validate_runtime
from app.container import AppContainer, build_container
from app.observability.logging import configure_logging, log_event
from app.services.restaurant import DEFAULT_RESTAURANT

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, container: AppContainer | None = None) -> FastAPI:
    """`container` lets tests supply their own repository and speech-to-text."""
    if container is not None:
        settings = container.settings
    settings = settings or load_settings()
    configure_logging(settings)
    validate_runtime(settings, DEFAULT_RESTAURANT)
    if settings.brain_fixed_now:
        log_event(logger, "warning_fixed_clock", logging.WARNING, note="BRAIN_FIXED_NOW is set (demo only)")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = container or build_container(settings)
        app.state.container = active
        runtime.register(active)
        await active.start()
        log_event(logger, "app_started", env=settings.app_env)
        yield
        active.begin_shutdown()
        await active.aclose()
        runtime.clear()
        log_event(logger, "app_stopped")

    production = settings.app_env == "production"
    app = FastAPI(
        title="The Copper Pot voice receptionist",
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET"], allow_headers=[]
    )
    app.include_router(health.router)
    app.include_router(ws.router)
    return app
