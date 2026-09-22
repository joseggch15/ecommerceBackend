"""Pruebas de integración del módulo de reseñas, preguntas y reputación."""

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


async def _context(
    client: AsyncClient, db_session: AsyncSession, *, deliver: bool = True
) -> dict[str, Any]:
    """Crea catálogo, orden pagada y (opcionalmente) entregada; devuelve tokens e ids."""
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
                "title": "Producto Reseña",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-REV", "price": "25000", "stock": 10}],
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
    if deliver:
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

    return {
        "buyer": buyer_token,
        "seller": seller_token,
        "product_id": product["id"],
        "sale_id": sale_id,
    }


async def test_review_requires_delivered_purchase(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session, deliver=False)
    resp = await integration_client.post(
        "/api/v1/reviews",
        json={"product_id": ctx["product_id"], "rating": 5},
        headers=_auth(ctx["buyer"]),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "purchase_required"


async def test_review_updates_reputation(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)
    url = f"/api/v1/products/{ctx['product_id']}/reviews"

    created = await integration_client.post(
        "/api/v1/reviews",
        json={
            "product_id": ctx["product_id"],
            "rating": 4,
            "title": "Buen producto",
            "body": "Llego en buen estado",
        },
        headers=_auth(ctx["buyer"]),
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["verified_purchase"] is True
    assert review["rating"] == 4

    listed = await integration_client.get(url)
    assert listed.status_code == 200
    body = listed.json()
    assert body["rating_count"] == 1
    assert Decimal(body["rating_average"]) == Decimal("4.00")
    assert body["items"][0]["id"] == review["id"]

    # No se puede reseñar dos veces el mismo producto...
    again = await integration_client.post(
        "/api/v1/reviews",
        json={"product_id": ctx["product_id"], "rating": 1},
        headers=_auth(ctx["buyer"]),
    )
    assert again.status_code == 409
    assert again.json()["code"] == "review_exists"

    # ...pero sí editar la propia, y la reputación se recalcula.
    updated = await integration_client.patch(
        f"/api/v1/reviews/{review['id']}", json={"rating": 2}, headers=_auth(ctx["buyer"])
    )
    assert updated.status_code == 200
    assert updated.json()["rating"] == 2
    after = (await integration_client.get(url)).json()
    assert Decimal(after["rating_average"]) == Decimal("2.00")

    # Un usuario ajeno no puede editar la reseña.
    other = await _register(integration_client, "other@example.com", "Otro")
    forbidden = await integration_client.patch(
        f"/api/v1/reviews/{review['id']}", json={"rating": 5}, headers=_auth(other)
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["code"] == "review_not_found"

    # Al borrarla, la reputación vuelve a cero.
    deleted = await integration_client.delete(
        f"/api/v1/reviews/{review['id']}", headers=_auth(ctx["buyer"])
    )
    assert deleted.status_code == 204
    empty = (await integration_client.get(url)).json()
    assert empty["rating_count"] == 0
    assert empty["rating_average"] is None


async def test_question_and_seller_answer(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)
    asked = await integration_client.post(
        f"/api/v1/products/{ctx['product_id']}/questions",
        json={"body": "¿Tiene garantía?"},
        headers=_auth(ctx["buyer"]),
    )
    assert asked.status_code == 201, asked.text
    question_id = asked.json()["id"]

    # El comprador no tiene tienda: no puede responder.
    from_buyer = await integration_client.post(
        f"/api/v1/questions/{question_id}/answers",
        json={"body": "No lo se"},
        headers=_auth(ctx["buyer"]),
    )
    assert from_buyer.status_code == 403
    assert from_buyer.json()["code"] == "store_required"

    answered = await integration_client.post(
        f"/api/v1/questions/{question_id}/answers",
        json={"body": "Si, 12 meses."},
        headers=_auth(ctx["seller"]),
    )
    assert answered.status_code == 201, answered.text

    listed = await integration_client.get(f"/api/v1/products/{ctx['product_id']}/questions")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["body"] == "¿Tiene garantía?"
    assert items[0]["answers"][0]["body"] == "Si, 12 meses."
