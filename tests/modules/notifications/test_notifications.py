"""Pruebas de integración del módulo de notificaciones (in-app, emails y cola)."""

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


async def _paid_order(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Prepara catálogo, compra y pago confirmado; devuelve tokens e ids."""
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
                "title": "Producto Notif",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-NOT", "price": "25000", "stock": 10}],
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
    return {"admin": admin_token, "buyer": buyer_token, "order_id": order["id"]}


async def test_order_paid_notifies_buyer(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)

    listed = await integration_client.get("/api/v1/notifications", headers=_auth(ctx["buyer"]))
    assert listed.status_code == 200
    body = listed.json()
    assert body["unread_count"] == 1
    assert len(body["items"]) == 1

    notification = body["items"][0]
    assert notification["type"] == "order_paid"
    assert notification["read_at"] is None
    assert notification["data"]["order_id"] == ctx["order_id"]

    unread = await integration_client.get(
        "/api/v1/notifications", params={"only_unread": True}, headers=_auth(ctx["buyer"])
    )
    assert len(unread.json()["items"]) == 1

    read = await integration_client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=_auth(ctx["buyer"])
    )
    assert read.status_code == 200
    assert read.json()["read_at"] is not None

    after = await integration_client.get("/api/v1/notifications", headers=_auth(ctx["buyer"]))
    assert after.json()["unread_count"] == 0

    # Otro usuario no puede leerla.
    other = await _register(integration_client, "other@example.com", "Otro")
    forbidden = await integration_client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=_auth(other)
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["code"] == "notification_not_found"


async def test_email_queue_is_processed(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)

    emails = await integration_client.get(
        "/api/v1/admin/notifications/emails", headers=_auth(ctx["admin"])
    )
    assert emails.status_code == 200
    # El más reciente es el del pago (en la cola van también los correos de verificación del alta).
    assert emails.json()[0]["type"] == "order_paid"
    assert emails.json()[0]["email_to"] == "buyer@example.com"
    assert emails.json()[0]["email_status"] == "queued"

    processed = await integration_client.post(
        "/api/v1/admin/notifications/process", headers=_auth(ctx["admin"])
    )
    assert processed.status_code == 200, processed.text
    result = processed.json()
    assert result["sent"] >= 1
    assert result["pending"] == 0

    after = await integration_client.get(
        "/api/v1/admin/notifications/emails", headers=_auth(ctx["admin"])
    )
    assert after.json()[0]["email_status"] == "sent"
    assert after.json()[0]["sent_at"] is not None


async def test_read_all_and_admin_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)

    # Un comprador no puede ver emails ni procesar la cola.
    forbidden_emails = await integration_client.get(
        "/api/v1/admin/notifications/emails", headers=_auth(ctx["buyer"])
    )
    assert forbidden_emails.status_code == 403

    forbidden_jobs = await integration_client.post(
        "/api/v1/admin/notifications/process", headers=_auth(ctx["buyer"])
    )
    assert forbidden_jobs.status_code == 403

    all_read = await integration_client.post(
        "/api/v1/notifications/read-all", headers=_auth(ctx["buyer"])
    )
    assert all_read.status_code == 200
    assert all_read.json()["unread_count"] == 0
