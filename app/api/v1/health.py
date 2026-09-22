"""Endpoint de health check: verifica PostgreSQL y Redis."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Formato de respuesta del health check."""

    status: str
    checks: dict[str, str]


async def check_database(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Verifica que PostgreSQL responda a una consulta mínima."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return {"status": "error"}
    return {"status": "ok"}


async def check_redis(redis_client: Redis = Depends(get_redis)) -> dict[str, str]:
    """Verifica que Redis responda a un ping."""
    try:
        await redis_client.ping()
    except Exception:
        return {"status": "error"}
    return {"status": "ok"}


@router.get("/live", summary="Liveness probe", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Liveness: el proceso está vivo (no toca dependencias)."""
    return HealthResponse(status="ok", checks={})


@router.get("/ready", summary="Readiness probe", response_model=HealthResponse)
@router.get("", summary="Health check", response_model=HealthResponse)
async def health(
    response: Response,
    database: dict[str, str] = Depends(check_database),
    cache: dict[str, str] = Depends(check_redis),
) -> HealthResponse:
    """Comprueba el estado de la aplicación y de sus dependencias (PostgreSQL y Redis)."""
    database_ok = database["status"] == "ok"
    cache_ok = cache["status"] == "ok"

    overall = "ok" if database_ok and cache_ok else "unhealthy"
    if not (database_ok and cache_ok):
        response.status_code = 503

    return HealthResponse(
        status=overall,
        checks={"database": database["status"], "redis": cache["status"]},
    )
