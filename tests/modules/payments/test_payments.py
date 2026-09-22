"""Pruebas de integración del módulo de pagos (sandbox, firma y webhooks)."""

from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserRole
from app.modules.payments.provider import SandboxPaymentProvider, sign_payload

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
    """El registro está limitado a 3/min por IP y aquí creamos varios usuarios."""
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _login(client: AsyncClient, email: str) -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    assert login.status_code == 200, f"login falló: {login.status_code} {login.text}"
    return str(login.json()["access_token"])


async def _register(client: AsyncClient, email: str, full_name: str = "Usuario") -> str:
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": full_name},
    )
    assert response.status_code == 201
    return await _login(client, email)


async def _create_order(
    client: AsyncClient, db_session: AsyncSession, *, price: str = "25000"
) -> tuple[str, str]:
    """Prepara catálogo, carrito y checkout; devuelve (token_comprador, id_orden)."""
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
                "title": "Producto Pago",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-PAY", "price": price, "stock": 10}],
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
            "/api/v1/orders",
            json={"shipping_address": ADDRESS},
            headers=_auth(buyer_token),
        )
    ).json()
    return buyer_token, str(order["id"])


async def _create_payment(client: AsyncClient, token: str, order_id: str) -> dict[str, Any]:
    response = await client.post(f"/api/v1/orders/{order_id}/payments", headers=_auth(token))
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_pay_order_with_sandbox(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)

    assert payment["provider"] == "sandbox"
    assert str(payment["provider_reference"]).startswith("sbx_")
    assert payment["status"] == "pending"
    assert str(payment["checkout_url"]).startswith("https://sandbox.marketplace.local/checkout/")
    assert Decimal(str(payment["amount"])) == Decimal("25000.00")

    paid = await integration_client.post(
        f"/api/v1/payments/{payment['id']}/simulate",
        params={"outcome": "succeeded"},
        headers=_auth(buyer_token),
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "succeeded"
    assert paid.json()["paid_at"] is not None

    order = (
        await integration_client.get(f"/api/v1/orders/{order_id}", headers=_auth(buyer_token))
    ).json()
    assert order["payment_status"] == "paid"
    assert order["status"] == "paid"


async def test_webhook_requires_valid_signature(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)
    raw = SandboxPaymentProvider.build_webhook_payload(
        str(payment["provider_reference"]), "succeeded"
    )

    missing = await integration_client.post(
        "/api/v1/webhooks/payments/sandbox",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert missing.status_code == 401
    assert missing.json()["code"] == "invalid_signature"

    wrong = await integration_client.post(
        "/api/v1/webhooks/payments/sandbox",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature": "deadbeef"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_signature"

    # Nada se aplicó: la orden sigue pendiente.
    order = (
        await integration_client.get(f"/api/v1/orders/{order_id}", headers=_auth(buyer_token))
    ).json()
    assert order["payment_status"] == "pending"


async def test_webhook_is_idempotent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)

    raw = SandboxPaymentProvider.build_webhook_payload(
        str(payment["provider_reference"]), "succeeded"
    )
    headers = {"Content-Type": "application/json", "X-Signature": sign_payload(raw)}

    first = await integration_client.post(
        "/api/v1/webhooks/payments/sandbox", content=raw, headers=headers
    )
    assert first.status_code == 200
    assert first.json() == {"received": True, "duplicate": False}

    # El proveedor reintenta el mismo evento: no se vuelve a aplicar.
    second = await integration_client.post(
        "/api/v1/webhooks/payments/sandbox", content=raw, headers=headers
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    order = (
        await integration_client.get(f"/api/v1/orders/{order_id}", headers=_auth(buyer_token))
    ).json()
    assert order["payment_status"] == "paid"
    assert order["status"] == "paid"


async def test_failed_payment_keeps_order_pending(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)

    failed = await integration_client.post(
        f"/api/v1/payments/{payment['id']}/simulate",
        params={"outcome": "failed"},
        headers=_auth(buyer_token),
    )
    assert failed.status_code == 200
    body = failed.json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "Card declined (sandbox)."
    assert body["paid_at"] is None

    # La orden sigue pendiente y se puede reintentar con otro intento de pago.
    order = (
        await integration_client.get(f"/api/v1/orders/{order_id}", headers=_auth(buyer_token))
    ).json()
    assert order["payment_status"] == "pending"
    assert order["status"] == "pending"

    retry = await integration_client.post(
        f"/api/v1/orders/{order_id}/payments", headers=_auth(buyer_token)
    )
    assert retry.status_code == 201
    assert retry.json()["id"] != payment["id"]


async def test_refund_after_payment(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)
    simulate = f"/api/v1/payments/{payment['id']}/simulate"

    await integration_client.post(
        simulate, params={"outcome": "succeeded"}, headers=_auth(buyer_token)
    )
    refunded = await integration_client.post(
        simulate, params={"outcome": "refunded"}, headers=_auth(buyer_token)
    )
    assert refunded.status_code == 200
    assert refunded.json()["status"] == "refunded"

    order = (
        await integration_client.get(f"/api/v1/orders/{order_id}", headers=_auth(buyer_token))
    ).json()
    assert order["payment_status"] == "refunded"
    assert order["status"] == "refunded"


async def test_cannot_pay_a_paid_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)
    await integration_client.post(
        f"/api/v1/payments/{payment['id']}/simulate",
        params={"outcome": "succeeded"},
        headers=_auth(buyer_token),
    )

    again = await integration_client.post(
        f"/api/v1/orders/{order_id}/payments", headers=_auth(buyer_token)
    )
    assert again.status_code == 409
    assert again.json()["code"] == "order_already_paid"


async def test_create_payment_is_idempotent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    headers = {**_auth(buyer_token), "Idempotency-Key": "pay-123"}

    first = await integration_client.post(f"/api/v1/orders/{order_id}/payments", headers=headers)
    second = await integration_client.post(f"/api/v1/orders/{order_id}/payments", headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = await integration_client.get(
        f"/api/v1/orders/{order_id}/payments", headers=_auth(buyer_token)
    )
    assert len(listed.json()) == 1


async def test_payment_is_private(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    buyer_token, order_id = await _create_order(integration_client, db_session)
    payment = await _create_payment(integration_client, buyer_token, order_id)

    other_token = await _register(integration_client, "other@example.com", "Otro")
    resp = await integration_client.get(
        f"/api/v1/payments/{payment['id']}", headers=_auth(other_token)
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "payment_not_found"
