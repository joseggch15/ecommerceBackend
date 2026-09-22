"""Pruebas de integración del módulo de catálogo (categorías y atributos)."""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserRole


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


async def test_list_categories_empty(integration_client: AsyncClient) -> None:
    resp = await integration_client.get("/api/v1/catalog/categories")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_category_requires_admin(integration_client: AsyncClient) -> None:
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "c@example.com", "password": "secret123", "full_name": "C"},
    )
    login = await integration_client.post(
        "/api/v1/auth/login", json={"email": "c@example.com", "password": "secret123"}
    )
    token = str(login.json()["access_token"])

    resp = await integration_client.post(
        "/api/v1/catalog/categories", json={"name": "Ropa"}, headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_create_and_update_category(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_promote(integration_client, db_session)

    created = await integration_client.post(
        "/api/v1/catalog/categories",
        json={"name": "Ropa", "commission_rate": "12.5"},
        headers=_auth(token),
    )
    assert created.status_code == 201
    assert created.json()["slug"] == "ropa"
    assert Decimal(str(created.json()["commission_rate"])) == Decimal("12.5")

    updated = await integration_client.patch(
        f"/api/v1/catalog/categories/{created.json()['id']}",
        json={"name": "Ropa y Moda"},
        headers=_auth(token),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ropa y Moda"


async def test_delete_category_with_children_conflict(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_promote(integration_client, db_session)

    parent = (
        await integration_client.post(
            "/api/v1/catalog/categories", json={"name": "Electrónica"}, headers=_auth(token)
        )
    ).json()
    await integration_client.post(
        "/api/v1/catalog/categories",
        json={"name": "Celulares", "parent_id": parent["id"]},
        headers=_auth(token),
    )

    resp = await integration_client.delete(
        f"/api/v1/catalog/categories/{parent['id']}", headers=_auth(token)
    )
    assert resp.status_code == 409


async def test_attribute_assignment(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_promote(integration_client, db_session)

    category = (
        await integration_client.post(
            "/api/v1/catalog/categories", json={"name": "Ropa"}, headers=_auth(token)
        )
    ).json()
    attr = (
        await integration_client.post(
            "/api/v1/catalog/attributes",
            json={"name": "Talla", "type": "select"},
            headers=_auth(token),
        )
    ).json()

    assigned = await integration_client.post(
        f"/api/v1/catalog/categories/{category['id']}/attributes",
        json={"attribute_id": attr["id"], "is_required": True},
        headers=_auth(token),
    )
    assert assigned.status_code == 201
    assert assigned.json()["is_required"] is True

    listed = await integration_client.get(f"/api/v1/catalog/categories/{category['id']}/attributes")
    assert listed.status_code == 200
    attrs = listed.json()
    assert len(attrs) == 1
    assert attrs[0]["name"] == "Talla"
    assert attrs[0]["type"] == "select"
