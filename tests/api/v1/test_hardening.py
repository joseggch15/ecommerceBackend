"""Pruebas de endurecimiento: cabeceras de seguridad y sondas de salud."""

from httpx import AsyncClient


async def test_liveness_does_not_need_dependencies(client: AsyncClient) -> None:
    """Liveness responde aunque no haya base de datos ni Redis."""
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}


async def test_security_headers_are_present(client: AsyncClient) -> None:
    """Toda respuesta lleva las cabeceras de seguridad de la API."""
    response = await client.get("/api/v1/health/live")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "geolocation=()" in response.headers["permissions-policy"]
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert response.headers["cross-origin-resource-policy"] == "same-site"
    # Se conserva el request id del middleware de contexto.
    assert response.headers["x-request-id"]


async def test_hsts_only_in_production(client: AsyncClient) -> None:
    """En desarrollo no se fuerza HTTPS (el navegador no debe cachear HSTS)."""
    response = await client.get("/api/v1/health/live")
    assert "strict-transport-security" not in response.headers


async def test_readiness_checks_dependencies(integration_client: AsyncClient) -> None:
    """Readiness comprueba PostgreSQL y Redis (y `/health` es un alias)."""
    ready = await integration_client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}

    alias = await integration_client.get("/api/v1/health")
    assert alias.status_code == 200
    assert alias.json()["status"] == "ok"
