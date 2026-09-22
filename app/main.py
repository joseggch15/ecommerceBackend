"""Punto de entrada de la aplicación FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.redis import redis_client
from app.core.storage import ensure_bucket

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestiona el ciclo de vida de la aplicación (arranque y apagado)."""
    logger.info("app_startup", environment=settings.ENVIRONMENT)
    ensure_bucket()
    yield
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
