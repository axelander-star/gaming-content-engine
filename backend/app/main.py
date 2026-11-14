"""FastAPI application factory. Run with ``uvicorn app.main:app``."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from api.agents import router as agents_router
from api.auth import router as auth_router
from api.channels import router as channels_router
from api.health import router as health_router
from api.overview import router as overview_router
from api.rights import router as rights_router
from api.settings import router as settings_router
from api.trends import router as trends_router
from api.users import router as users_router
from core.config import get_settings
from core.logging import configure_logging

API_PREFIX = "/api"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    is_prod = settings.app_env == "production"
    app = FastAPI(
        title="Gaming Content Engine API",
        version="0.6.0",
        # Interactive docs only outside production.
        docs_url=None if is_prod else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if is_prod else f"{API_PREFIX}/openapi.json",
    )
    for router in (
        health_router,
        auth_router,
        users_router,
        settings_router,
        channels_router,
        overview_router,
        agents_router,
        trends_router,
        rights_router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    logging.getLogger(__name__).info(
        "api started",
        extra={
            "app_env": settings.app_env,
            "publishing_mode": settings.publishing_mode,
            "auto_publish_enabled": settings.auto_publish_enabled,
            "emergency_stop": settings.emergency_stop,
        },
    )
    return app


app = create_app()
