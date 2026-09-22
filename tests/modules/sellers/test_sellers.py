"""Pruebas de integración del módulo de vendedores."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserRole


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(client: AsyncClient, email: str = "vendedor@example.com") -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": "Vendedor"},
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    return str(login.json()["access_token"])


async def _register_and_promote(
    client: AsyncClient, db_session: AsyncSession, email: str = "admin@example.com"
) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": "Admin"},
    )
    result = await db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    user.role = UserRole.ADMIN
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    return str(login.json()["access_token"])


async def test_create_store_requires_auth(integration_client: AsyncClient) -> None:
    resp = await integration_client.post("/api/v1/sellers/me", json={"name": "Mi Tienda"})
    assert resp.status_code == 401


async def test_create_and_get_store(integration_client: AsyncClient) -> None:
    token = await _register_and_login(integration_client)

    created = await integration_client.post(
        "/api/v1/sellers/me",
        json={"name": "Mi Tienda", "description": "Descripción"},
        headers=_auth(token),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Mi Tienda"
    assert body["slug"] == "mi-tienda"
    assert body["status"] == "pending"

    got = await integration_client.get("/api/v1/sellers/me", headers=_auth(token))
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


async def test_create_duplicate_store_conflict(integration_client: AsyncClient) -> None:
    token = await _register_and_login(integration_client)
    await integration_client.post(
        "/api/v1/sellers/me", json={"name": "Tienda"}, headers=_auth(token)
    )
    resp = await integration_client.post(
        "/api/v1/sellers/me", json={"name": "Otra"}, headers=_auth(token)
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "store_already_exists"


async def test_admin_approves_store(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token = await _register_and_login(integration_client, email="vendedor@example.com")
    admin_token = await _register_and_promote(
        integration_client, db_session, email="admin@example.com"
    )

    store = (
        await integration_client.post(
            "/api/v1/sellers/me", json={"name": "Tienda"}, headers=_auth(seller_token)
        )
    ).json()

    # Un vendedor no puede aprobar (no es admin).
    forbidden = await integration_client.post(
        f"/api/v1/sellers/{store['id']}/approve", headers=_auth(seller_token)
    )
    assert forbidden.status_code == 403

    approved = await integration_client.post(
        f"/api/v1/sellers/{store['id']}/approve", headers=_auth(admin_token)
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


async def test_admin_rejects_store(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token = await _register_and_login(integration_client, email="vendedor@example.com")
    admin_token = await _register_and_promote(
        integration_client, db_session, email="admin@example.com"
    )

    store = (
        await integration_client.post(
            "/api/v1/sellers/me", json={"name": "Tienda"}, headers=_auth(seller_token)
        )
    ).json()

    rejected = await integration_client.post(
        f"/api/v1/sellers/{store['id']}/reject", headers=_auth(admin_token)
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
