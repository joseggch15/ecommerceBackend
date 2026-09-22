"""Pruebas de integración del módulo de administración."""

from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserRole

TEST_REDIS_URL = "redis://localhost:6379/1"
ADDRESS: dict[str, str] = {
    "recipient": "Juan Perez",
    "line1": "Calle 123 #45-67",
    "city": "Bogota",
    "country": "CO",
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _reset_register_rate_limit() -> None:
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _login(client: AsyncClient, email: str) -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _register(client: AsyncClient, email: str, full_name: str) -> str:
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return await _login(client, email)


async def _context(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Compra entregada y reseñada; devuelve tokens e ids para moderar."""
    await _reset_register_rate_limit()
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "secret123", "full_name": "Admin"},
    )
    result = await db_session.execute(select(User).where(User.email == "admin@example.com"))
    result.scalar_one().role = UserRole.ADMIN
    await db_session.commit()
    admin_token = await _login(client, "admin@example.com")

    category = (
        await client.post(
            "/api/v1/catalog/categories",
            json={"name": "Ropa", "commission_rate": "10"},
            headers=_auth(admin_token),
        )
    ).json()
    seller_token = await _register(client, "seller@example.com", "Vendedor")
    store = (
        await client.post(
            "/api/v1/sellers/me", json={"name": "Tienda"}, headers=_auth(seller_token)
        )
    ).json()
    await client.post(f"/api/v1/sellers/{store['id']}/approve", headers=_auth(admin_token))

    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": "Producto Admin",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-ADM", "price": "25000", "stock": 10}],
            },
            headers=_auth(seller_token),
        )
    ).json()
    await client.post(
        f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(seller_token)
    )

    buyer_token = await _register(client, "buyer@example.com", "Comprador")
    await client.post(
        "/api/v1/cart/items",
        json={"variant_id": product["variants"][0]["id"], "quantity": 1},
        headers=_auth(buyer_token),
    )
    order = (
        await client.post(
            "/api/v1/orders", json={"shipping_address": ADDRESS}, headers=_auth(buyer_token)
        )
    ).json()
    payment = (
        await client.post(f"/api/v1/orders/{order['id']}/payments", headers=_auth(buyer_token))
    ).json()
    await client.post(
        f"/api/v1/payments/{payment['id']}/simulate",
        params={"outcome": "succeeded"},
        headers=_auth(buyer_token),
    )

    sales = (await client.get("/api/v1/seller/orders", headers=_auth(seller_token))).json()
    sale_id = sales["items"][0]["id"]
    await client.post(
        f"/api/v1/seller/orders/{sale_id}/shipment",
        json={"carrier": "Servientrega"},
        headers=_auth(seller_token),
    )
    for status in ("shipped", "in_transit", "delivered"):
        await client.post(
            f"/api/v1/seller/orders/{sale_id}/shipment/status",
            params={"status": status},
            headers=_auth(seller_token),
        )

    review = (
        await client.post(
            "/api/v1/reviews",
            json={"product_id": product["id"], "rating": 5, "title": "Excelente"},
            headers=_auth(buyer_token),
        )
    ).json()
    return {
        "admin": admin_token,
        "buyer": buyer_token,
        "seller": seller_token,
        "store_id": store["id"],
        "product_id": product["id"],
        "review_id": review["id"],
    }


async def test_moderation_is_admin_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)

    for path in (
        f"/api/v1/admin/products/{ctx['product_id']}/suspend",
        "/api/v1/admin/metrics",
        "/api/v1/admin/actions",
    ):
        response = await integration_client.get(path, headers=_auth(ctx["buyer"]))
        assert response.status_code in {403, 405}

    suspend = await integration_client.post(
        f"/api/v1/admin/products/{ctx['product_id']}/suspend", headers=_auth(ctx["buyer"])
    )
    assert suspend.status_code == 403

    anonymous = await integration_client.get("/api/v1/admin/metrics")
    assert anonymous.status_code == 401


async def test_product_moderation_and_metrics(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)

    metrics = (
        await integration_client.get("/api/v1/admin/metrics", headers=_auth(ctx["admin"]))
    ).json()
    assert metrics["users"] == 3
    assert metrics["stores"] == 1
    assert metrics["products"] == 1
    assert Decimal(metrics["gmv"]) == Decimal("25000.00")
    assert Decimal(metrics["commission"]) == Decimal("2500.00")
    assert metrics["orders_by_status"]["completed"] == 1
    assert metrics["top_stores"][0]["store_id"] == ctx["store_id"]
    assert Decimal(metrics["top_stores"][0]["sales"]) == Decimal("25000.00")

    suspended = await integration_client.post(
        f"/api/v1/admin/products/{ctx['product_id']}/suspend",
        json={"reason": "Contenido inapropiado"},
        headers=_auth(ctx["admin"]),
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["action"] == "product.suspend"
    assert suspended.json()["reason"] == "Contenido inapropiado"
    assert suspended.json()["data"]["status"] == "paused"

    after = (
        await integration_client.get("/api/v1/admin/metrics", headers=_auth(ctx["admin"]))
    ).json()
    assert after["products"] == 0  # el producto pausado ya no cuenta como activo

    restored = await integration_client.post(
        f"/api/v1/admin/products/{ctx['product_id']}/restore", headers=_auth(ctx["admin"])
    )
    assert restored.json()["action"] == "product.restore"

    store_action = await integration_client.post(
        f"/api/v1/admin/stores/{ctx['store_id']}/suspend", headers=_auth(ctx["admin"])
    )
    assert store_action.json()["action"] == "store.suspend"

    actions = (
        await integration_client.get("/api/v1/admin/actions", headers=_auth(ctx["admin"]))
    ).json()
    assert [action["action"] for action in actions] == [
        "store.suspend",
        "product.restore",
        "product.suspend",
    ]


async def test_review_moderation_updates_reputation(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)
    url = f"/api/v1/products/{ctx['product_id']}/reviews"

    assert (await integration_client.get(url)).json()["rating_count"] == 1

    hidden = await integration_client.post(
        f"/api/v1/admin/reviews/{ctx['review_id']}/hide",
        json={"reason": "Spam"},
        headers=_auth(ctx["admin"]),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["action"] == "review.hide"
    assert (await integration_client.get(url)).json()["rating_count"] == 0

    published = await integration_client.post(
        f"/api/v1/admin/reviews/{ctx['review_id']}/publish", headers=_auth(ctx["admin"])
    )
    assert published.json()["action"] == "review.publish"
    assert (await integration_client.get(url)).json()["rating_count"] == 1
