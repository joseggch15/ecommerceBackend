"""Pruebas del endpoint de health check."""

from httpx import AsyncClient

from app.api.v1 import health as health_module
from app.main import app


async def test_health_ok(client: AsyncClient) -> None:
    """Debe devolver 200 con status 'ok' cuando PostgreSQL y Redis están sanos."""

    async def db_ok() -> dict[str, str]:
        return {"status": "ok"}

    async def cache_ok() -> dict[str, str]:
        return {"status": "ok"}

    app.dependency_overrides[health_module.check_database] = db_ok
    app.dependency_overrides[health_module.check_redis] = cache_ok

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok"},
    }


async def test_health_unhealthy(client: AsyncClient) -> None:
    """Debe devolver 503 con status 'unhealthy' cuando una dependencia falla."""

    async def db_error() -> dict[str, str]:
        return {"status": "error"}

    async def cache_ok() -> dict[str, str]:
        return {"status": "ok"}

    app.dependency_overrides[health_module.check_database] = db_error
    app.dependency_overrides[health_module.check_redis] = cache_ok

    response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["checks"]["database"] == "error"
