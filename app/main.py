import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import __version__
from app.api.deps import WriteAuth
from app.api.routes import alerts, analytics, endpoints, health, live, system
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_extra, request_id_ctx
from app.db.session import create_engine, create_sessionmaker
from app.services.analytics import AnalyticsUnavailableError
from app.services.checker import HealthChecker
from app.services.demo_seed import seed_demo_endpoints
from app.services.events import EventBus
from app.services.monitor import MonitorService
from app.services.notifier import build_email_notifier, build_notifier
from app.services.scheduler import Scheduler

logger = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"
# Paths the single-page-app fallback must never swallow.
RESERVED_PREFIXES = ("api/", "ws", "docs", "redoc", "openapi.json", "metrics", "health", "demo/")


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """App factory. `http_transport` lets tests swap the outbound network for a mock."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    events = EventBus()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(
            settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow
        )
        sessionmaker = create_sessionmaker(engine)
        http_client = httpx.AsyncClient(
            transport=http_transport,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=settings.max_concurrent_checks, max_keepalive_connections=20
            ),
            headers={"User-Agent": f"API-Sentinel/{__version__}"},
        )
        email_notifier = build_email_notifier(settings, http_client)
        notifier = build_notifier(settings, http_client, email_notifier)
        monitor = MonitorService(
            sessionmaker, HealthChecker(http_client), notifier, settings, events=events
        )
        scheduler = Scheduler(monitor, settings)

        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.monitor = monitor
        app.state.scheduler = scheduler
        app.state.events = events
        app.state.email_notifier = email_notifier

        if settings.seed_demo and settings.public_base_url:
            try:
                await seed_demo_endpoints(sessionmaker, settings.public_base_url)
            except Exception:
                logger.exception("demo seeding failed")
        if settings.scheduler_enabled:
            await scheduler.start()
        logger.info("API Sentinel started", extra=log_extra(version=__version__, env=settings.environment))
        try:
            yield
        finally:
            await scheduler.stop()
            await http_client.aclose()
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "API monitoring & reliability platform: scheduled async health checks, retries with "
            "exponential backoff, SLO tracking, latency anomaly detection, TLS expiry monitoring, "
            "maintenance windows, a public status page and real-time WebSocket updates."
        ),
        lifespan=lifespan,
    )
    app.state.events = events

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            path = request.url.path
            if path.startswith("/api/") or path.startswith("/health/ready"):
                logger.info(
                    "request",
                    extra=log_extra(
                        method=request.method,
                        path=path,
                        status=response.status_code,
                        duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    ),
                )
            return response
        finally:
            request_id_ctx.reset(token)

    @app.exception_handler(AnalyticsUnavailableError)
    async def _analytics_unavailable(_request: Request, exc: AnalyticsUnavailableError):
        return JSONResponse(status_code=501, content={"detail": str(exc)})

    api_prefix = "/api/v1"
    app.include_router(endpoints.router, prefix=api_prefix)
    app.include_router(analytics.router, prefix=api_prefix)
    app.include_router(alerts.router, prefix=api_prefix)
    app.include_router(system.router, prefix=api_prefix)
    app.include_router(health.router)
    app.include_router(live.router)

    if settings.enable_demo_target:
        from demo.flaky_api import chaos_router, public_router

        app.include_router(public_router, prefix="/demo")
        app.include_router(chaos_router, prefix="/demo", dependencies=[WriteAuth])

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built React app (frontend/ -> app/static) with client-side routing fallback."""
    index = STATIC_DIR / "index.html"
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(RESERVED_PREFIXES):
            raise HTTPException(status_code=404)
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and STATIC_DIR.resolve() in candidate.parents:
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<h1>API Sentinel</h1><p>Frontend not built. Run <code>npm run build</code> in "
            "<code>frontend/</code>, or use the Docker image. API docs: <a href='/docs'>/docs</a></p>"
        )


app = create_app()
