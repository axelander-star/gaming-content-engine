"""FastAPI application factory. Run with ``uvicorn app.main:app``."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from api.accounts import router as accounts_router
from api.agents import router as agents_router
from api.ai import router as ai_router
from api.analytics import router as analytics_router
from api.approval import router as approval_router
from api.assistant import planning_router
from api.assistant import router as assistant_router
from api.auth import router as auth_router
from api.calendar import router as calendar_router
from api.campaigns import router as campaigns_router
from api.channel_setup import router as channel_setup_router
from api.channels import oauth_router
from api.channels import router as channels_router
from api.comments import router as comments_router
from api.competitors import router as competitors_router
from api.health import router as health_router
from api.library import router as library_router
from api.notifications import router as notifications_router
from api.overview import router as overview_router
from api.production import router as production_router
from api.projects import router as projects_router
from api.publishing import router as publishing_router
from api.research import router as research_router
from api.rights import router as rights_router
from api.settings import router as settings_router
from api.system import router as system_router
from api.trends import router as trends_router
from api.uploads import router as uploads_router
from api.users import router as users_router
from core import access_guard
from core.config import get_settings
from core.logging import configure_logging
from services.monitoring import count_http_error
from services.queue import get_redis

API_PREFIX = "/api"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    is_prod = settings.app_env == "production"
    app = FastAPI(
        title="Gaming Content Engine API",
        version="0.15.0",
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
        oauth_router,
        overview_router,
        agents_router,
        trends_router,
        rights_router,
        production_router,
        publishing_router,
        analytics_router,
        system_router,
        uploads_router,
        projects_router,
        ai_router,
        assistant_router,
        planning_router,
        research_router,
        calendar_router,
        library_router,
        approval_router,
        campaigns_router,
        channel_setup_router,
        accounts_router,
        comments_router,
        competitors_router,
        notifications_router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    if settings.access_guard == "cloudflare":

        @app.middleware("http")
        async def require_cloudflare_access(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            """Second check behind Cloudflare Access (private operation)."""
            if not access_guard.is_exempt(request.url.path):
                token = request.headers.get(access_guard.HEADER) or request.cookies.get(
                    access_guard.COOKIE
                )
                try:
                    # Key lookup may hit the network (cached for an hour): keep it
                    # off the event loop.
                    await run_in_threadpool(access_guard.verify, settings, token)
                except access_guard.AccessDeniedError as exc:
                    logging.getLogger(__name__).warning(
                        "access denied", extra={"path": request.url.path, "reason": str(exc)}
                    )
                    return JSONResponse({"detail": "Access denied"}, status_code=403)
            return await call_next(request)

    @app.middleware("http")
    async def count_server_errors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Count 5xx responses for the error monitoring (Phase 15)."""
        try:
            response = await call_next(request)
        except Exception:
            _count_error()
            raise
        if response.status_code >= 500:
            _count_error()
        return response

    logging.getLogger(__name__).info(
        "api started",
        extra={
            "app_env": settings.app_env,
            "publishing_mode": settings.publishing_mode,
            "auto_publish_enabled": settings.auto_publish_enabled,
            "emergency_stop": settings.emergency_stop,
            "access_guard": settings.access_guard,
            "single_user_mode": settings.single_user_mode,
        },
    )
    return app


def _count_error() -> None:
    try:
        count_http_error(get_redis())
    except RedisError:
        logging.getLogger(__name__).warning("could not count server error")


app = create_app()
