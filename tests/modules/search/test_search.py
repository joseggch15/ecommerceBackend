"""Pruebas de integración del módulo de búsqueda."""

import uuid
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Product
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
    client: AsyncClient,
    token: str,
    category_id: str,
    title: str,
    price: str,
    brand: str | None = None,
) -> dict[str, Any]:
    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": title,
                "category_id": category_id,
                "brand": brand,
                "variants": [{"sku": f"SKU-{title}", "price": price, "stock": 5}],
            },
            headers=_auth(token),
        )
    ).json()
    await client.post(f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(token))
    return dict(product)


ADDRESS: dict[str, str] = {
    "recipient": "Juan Perez",
    "line1": "Calle 123 #45-67",
    "city": "Bogota",
    "country": "CO",
}


async def _reset_register_rate_limit() -> None:
    """El registro está limitado a 3/min por IP y aquí se crean varios usuarios."""
    redis: Redis = Redis.from_url("redis://localhost:6379/1", decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _register_buyer(client: AsyncClient, email: str) -> str:
    """Crea un comprador y devuelve su access token."""
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": "Comprador"},
    )
    assert response.status_code == 201, response.text
    return await _login(client, email)


async def _search_titles(client: AsyncClient) -> dict[str, Any]:
    """Resultados de búsqueda indexados por título (para leer un item concreto)."""
    body = (await client.get("/api/v1/catalog/search")).json()
    return {item["title"]: item for item in body["items"]}


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


async def test_search_returns_store_name_and_reputation(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, _, category_id = await _setup(integration_client, db_session)
    product = await _create_and_publish(
        integration_client, seller_token, category_id, "Camiseta Azul", "25000"
    )

    # La reputación la mantiene el módulo de reseñas: aquí se fija directamente para comprobar que
    # la búsqueda la devuelve, sin montar la compra completa y su reseña.
    stored = (
        await db_session.execute(select(Product).where(Product.id == uuid.UUID(product["id"])))
    ).scalar_one()
    stored.rating_average = Decimal("4.50")
    stored.rating_count = 3
    await db_session.commit()

    resp = await integration_client.get("/api/v1/catalog/search", params={"q": "camiseta"})
    item = resp.json()["items"][0]
    assert item["store_name"] == "Tienda"
    assert Decimal(str(item["rating_average"])) == Decimal("4.50")
    assert item["review_count"] == 3


async def test_search_facets_count_categories_brands_and_price(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    seller_token, admin_token, clothing = await _setup(integration_client, db_session)
    await _create_and_publish(
        integration_client, seller_token, clothing, "Camiseta Azul", "25000", brand="Acme"
    )
    await _create_and_publish(
        integration_client, seller_token, clothing, "Camiseta Roja", "30000", brand="Acme"
    )
    shoes = (
        await integration_client.post(
            "/api/v1/catalog/categories", json={"name": "Zapatos"}, headers=_auth(admin_token)
        )
    ).json()
    await _create_and_publish(
        integration_client, seller_token, shoes["id"], "Tenis", "80000", brand="Beta"
    )

    body = (await integration_client.get("/api/v1/catalog/search")).json()
    assert {row["name"]: row["count"] for row in body["facets"]["categories"]} == {
        "Ropa": 2,
        "Zapatos": 1,
    }
    assert {row["brand"]: row["count"] for row in body["facets"]["brands"]} == {
        "Acme": 2,
        "Beta": 1,
    }
    assert Decimal(str(body["facets"]["price"]["min"])) == Decimal("25000.00")
    assert Decimal(str(body["facets"]["price"]["max"])) == Decimal("80000.00")

    # Con la categoría filtrada: su faceta sigue mostrando todas las categorías (ese filtro se
    # excluye de su propio conteo) y la de marcas sí respeta el filtro.
    filtered = (
        await integration_client.get(
            "/api/v1/catalog/search", params={"category_id": shoes["id"]}
        )
    ).json()
    assert {row["name"]: row["count"] for row in filtered["facets"]["categories"]} == {
        "Ropa": 2,
        "Zapatos": 1,
    }
    assert {row["brand"]: row["count"] for row in filtered["facets"]["brands"]} == {"Beta": 1}
    assert [item["title"] for item in filtered["items"]] == ["Tenis"]

    # Con la marca filtrada, la faceta de marcas tampoco se filtra a sí misma.
    by_brand = (
        await integration_client.get("/api/v1/catalog/search", params={"brand": "Acme"})
    ).json()
    assert {row["brand"]: row["count"] for row in by_brand["facets"]["brands"]} == {
        "Acme": 2,
        "Beta": 1,
    }
    assert {row["name"]: row["count"] for row in by_brand["facets"]["categories"]} == {"Ropa": 2}
    assert len(by_brand["items"]) == 2


async def test_sold_count_counts_only_paid_orders(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`sold_count` suma unidades de órdenes **pagadas** y deja de contar al reembolsar.

    Es la insignia «más vendido»: sale de agregar las líneas de orden pagadas, no de un contador
    denormalizado que se pueda desincronizar (apartado «datos que faltan para la interfaz»).
    """
    seller_token, _, category_id = await _setup(integration_client, db_session)
    product = await _create_and_publish(
        integration_client, seller_token, category_id, "Camiseta Azul", "25000"
    )

    # Sin ventas: cero (no se inventa ninguna cifra).
    assert (await _search_titles(integration_client))["Camiseta Azul"]["sold_count"] == 0

    buyer_token = await _register_buyer(integration_client, "buyer@example.com")
    await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": product["variants"][0]["id"], "quantity": 2},
        headers=_auth(buyer_token),
    )
    order = (
        await integration_client.post(
            "/api/v1/orders",
            json={"shipping_address": ADDRESS},
            headers=_auth(buyer_token),
        )
    ).json()

    # La orden existe pero todavía no está pagada: no cuenta como vendido.
    assert (await _search_titles(integration_client))["Camiseta Azul"]["sold_count"] == 0

    payment = (
        await integration_client.post(
            f"/api/v1/orders/{order['id']}/payments", headers=_auth(buyer_token)
        )
    ).json()
    paid = await integration_client.post(
        f"/api/v1/payments/{payment['id']}/simulate",
        params={"outcome": "succeeded"},
        headers=_auth(buyer_token),
    )
    assert paid.status_code == 200, paid.text

    assert (await _search_titles(integration_client))["Camiseta Azul"]["sold_count"] == 2
    detail = (
        await integration_client.get(f"/api/v1/catalog/products/{product['id']}")
    ).json()
    assert detail["sold_count"] == 2

    # Reembolso: el dinero volvió al comprador, así que esas unidades dejan de contar.
    refunded = await integration_client.post(
        f"/api/v1/payments/{payment['id']}/simulate",
        params={"outcome": "refunded"},
        headers=_auth(buyer_token),
    )
    assert refunded.status_code == 200, refunded.text

    assert (await _search_titles(integration_client))["Camiseta Azul"]["sold_count"] == 0
    detail = (
        await integration_client.get(f"/api/v1/catalog/products/{product['id']}")
    ).json()
    assert detail["sold_count"] == 0
