"""Punto de entrada de la aplicación FastAPI."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import async_session_factory, engine
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.redis import redis_client
from app.core.storage import ensure_bucket
from app.modules.notifications.worker import run_notification_worker

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestiona el ciclo de vida de la aplicación (arranque y apagado)."""
    logger.info("app_startup", environment=settings.ENVIRONMENT)
    ensure_bucket()

    # Worker de correos dentro del proceso: solo en desarrollo (`NOTIFICATION_WORKER_ENABLED`),
    # así los correos salen solos hacia Mailpit sin levantar un proceso aparte.
    worker_stop = asyncio.Event()
    worker_task: asyncio.Task[None] | None = None
    if settings.NOTIFICATION_WORKER_ENABLED:
        worker_task = asyncio.create_task(
            run_notification_worker(
                redis=redis_client,
                session_factory=async_session_factory,
                interval_seconds=settings.NOTIFICATION_WORKER_INTERVAL_SECONDS,
                stop=worker_stop,
            )
        )
        logger.info(
            "notification_worker_started",
            interval_seconds=settings.NOTIFICATION_WORKER_INTERVAL_SECONDS,
        )

    yield

    if worker_task is not None:
        worker_stop.set()
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
    await redis_client.aclose()
    await engine.dispose()
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Crea y configura la aplicación FastAPI (patrón factory)."""
    setup_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # HSTS solo en producción (en desarrollo se navega por http://localhost).
    hsts_max_age = (
        settings.HSTS_MAX_AGE_SECONDS
        if settings.ENVIRONMENT.lower() in {"production", "prod"}
        else None
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts_max_age=hsts_max_age)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
