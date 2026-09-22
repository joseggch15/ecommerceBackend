"""Pruebas de integración del módulo de búsqueda."""

from decimal import Decimal
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


async def _setup(client: AsyncClient, db_session: AsyncSession) -> tuple[str, str, str]:
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


async def _create_and_publish(
    client: AsyncClient, token: str, category_id: str, title: str, price: str
) -> dict[str, Any]:
    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": title,
                "category_id": category_id,
                "variants": [{"sku": f"SKU-{title}", "price": price, "stock": 5}],
            },
            headers=_auth(token),
        )
    ).json()
    await client.post(f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(token))
    return dict(product)


async def test_search_finds_published_product(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, _, category_id = await _setup(integration_client, db_session)
    await _create_and_publish(
        integration_client, seller_token, category_id, "Camiseta Azul", "25000"
    )

    resp = await integration_client.get("/api/v1/catalog/search", params={"q": "camiseta"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Camiseta Azul"
    assert Decimal(str(items[0]["min_price"])) == Decimal("25000.00")


async def test_search_filters_by_category(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, admin_token, category_id = await _setup(integration_client, db_session)
    await _create_and_publish(integration_client, seller_token, category_id, "Camiseta", "25000")

    other = (
        await integration_client.post(
            "/api/v1/catalog/categories", json={"name": "Zapatos"}, headers=_auth(admin_token)
        )
    ).json()
    await _create_and_publish(integration_client, seller_token, other["id"], "Tenis", "80000")

    resp = await integration_client.get(
        "/api/v1/catalog/search", params={"category_id": other["id"]}
    )
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Tenis"


async def test_search_suggest(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    seller_token, _, category_id = await _setup(integration_client, db_session)
    await _create_and_publish(integration_client, seller_token, category_id, "Camiseta", "25000")

    resp = await integration_client.get("/api/v1/catalog/search/suggest", params={"q": "cami"})
    assert resp.status_code == 200
    assert "Camiseta" in resp.json()
