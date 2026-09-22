"""Pruebas de integración de productos, variantes e imágenes."""

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


async def _setup_seller(client: AsyncClient, db_session: AsyncSession) -> str:
    """Registra vendedor + admin, crea y aprueba la tienda; devuelve el token del vendedor."""
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

    return seller_token


async def _create_category(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    admin_token = await _login(client, "admin@example.com")
    return dict(
        (
            await client.post(
                "/api/v1/catalog/categories", json={"name": "Ropa"}, headers=_auth(admin_token)
            )
        ).json()
    )


async def test_create_product_with_variants(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_seller(integration_client, db_session)
    category = await _create_category(integration_client, db_session)

    resp = await integration_client.post(
        "/api/v1/catalog/products",
        json={
            "title": "Camiseta",
            "category_id": category["id"],
            "variants": [
                {"sku": "CAM-M", "price": "25000", "stock": 10},
                {"sku": "CAM-L", "price": "26000", "stock": 5},
            ],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Camiseta"
    assert body["status"] == "draft"
    assert len(body["variants"]) == 2
    assert Decimal(str(body["variants"][0]["price"])) == Decimal("25000.00")


async def test_create_product_requires_approved_store(integration_client: AsyncClient) -> None:
    # Registra un vendedor sin tienda aprobada.
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "novato@example.com", "password": "secret123", "full_name": "Novato"},
    )
    token = await _login(integration_client, "novato@example.com")

    resp = await integration_client.post(
        "/api/v1/catalog/products",
        json={"title": "Producto", "category_id": "00000000-0000-0000-0000-000000000000"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_publish_product(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _setup_seller(integration_client, db_session)
    category = await _create_category(integration_client, db_session)

    product = (
        await integration_client.post(
            "/api/v1/catalog/products",
            json={"title": "Camiseta", "category_id": category["id"], "variants": []},
            headers=_auth(token),
        )
    ).json()

    published = await integration_client.post(
        f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(token)
    )
    assert published.status_code == 200
    assert published.json()["status"] == "active"


async def test_request_upload_url(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _setup_seller(integration_client, db_session)

    resp = await integration_client.post(
        "/api/v1/catalog/images/upload-url",
        json={"content_type": "image/png", "extension": ".png"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_key"].startswith("products/")
    assert body["upload_url"].startswith("http")
