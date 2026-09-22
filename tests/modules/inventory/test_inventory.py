"""Pruebas de integración del módulo de inventario (stock y reservas)."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserRole


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, email: str) -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    return str(login.json()["access_token"])


async def _setup_seller(client: AsyncClient, db_session: AsyncSession) -> tuple[str, str, str]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "seller@example.com", "password": "secret123", "full_name": "Seller"},
    )
    seller_token = await _login(client, "seller@example.com")

    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "secret123", "full_name": "Admin"},
    )
    result = await db_session.execute(select(User).where(User.email == "admin@example.com"))
    result.scalar_one().role = UserRole.ADMIN
    await db_session.commit()
    admin_token = await _login(client, "admin@example.com")

    store = (
        await client.post(
            "/api/v1/sellers/me", json={"name": "Tienda"}, headers=_auth(seller_token)
        )
    ).json()
    await client.post(f"/api/v1/sellers/{store['id']}/approve", headers=_auth(admin_token))

    category = (
        await client.post(
            "/api/v1/catalog/categories", json={"name": "Ropa"}, headers=_auth(admin_token)
        )
    ).json()
    return seller_token, admin_token, category["id"]


async def _create_product(
    client: AsyncClient, token: str, category_id: str, sku: str, stock: int
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/catalog/products",
        json={
            "title": f"Producto {sku}",
            "category_id": category_id,
            "variants": [{"sku": sku, "price": "25000", "stock": stock}],
        },
        headers=_auth(token),
    )
    return dict(resp.json())


async def test_initial_stock_comes_from_variant(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, _, category_id = await _setup_seller(integration_client, db_session)
    product = await _create_product(integration_client, seller_token, category_id, "SKU-1", 10)
    variant_id = product["variants"][0]["id"]

    resp = await integration_client.get(f"/api/v1/inventory/items/{variant_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity"] == 10
    assert body["reserved_quantity"] == 0
    assert body["available"] == 10


async def test_reserve_and_release(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, admin_token, category_id = await _setup_seller(integration_client, db_session)
    product = await _create_product(integration_client, seller_token, category_id, "SKU-2", 10)
    variant_id = product["variants"][0]["id"]

    reserved = await integration_client.post(
        f"/api/v1/inventory/items/{variant_id}/reserve",
        json={"quantity": 3},
        headers=_auth(admin_token),
    )
    assert reserved.status_code == 200
    assert reserved.json()["available"] == 7
    assert reserved.json()["reserved_quantity"] == 3

    released = await integration_client.post(
        f"/api/v1/inventory/items/{variant_id}/release",
        json={"quantity": 3},
        headers=_auth(admin_token),
    )
    assert released.status_code == 200
    assert released.json()["available"] == 10


async def test_reserve_insufficient_stock(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, admin_token, category_id = await _setup_seller(integration_client, db_session)
    product = await _create_product(integration_client, seller_token, category_id, "SKU-3", 2)
    variant_id = product["variants"][0]["id"]

    resp = await integration_client.post(
        f"/api/v1/inventory/items/{variant_id}/reserve",
        json={"quantity": 5},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "insufficient_stock"


async def test_adjust_stock(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    seller_token, admin_token, category_id = await _setup_seller(integration_client, db_session)
    product = await _create_product(integration_client, seller_token, category_id, "SKU-4", 10)
    variant_id = product["variants"][0]["id"]

    resp = await integration_client.post(
        f"/api/v1/inventory/items/{variant_id}/adjust",
        json={"delta": 5, "reason": "restock"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 15
