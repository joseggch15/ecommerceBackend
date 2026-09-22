"""Pruebas de integración del módulo de envíos (vendedor y comprador)."""

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


async def _register(client: AsyncClient, email: str, full_name: str) -> str:
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return await _login(client, email)


async def _paid_order(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Crea catálogo, carrito, orden y la paga; devuelve tokens e ids."""
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
                "title": "Producto Envio",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-SHIP", "price": "25000", "stock": 10}],
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
    return {
        "buyer": buyer_token,
        "seller": seller_token,
        "order_id": order["id"],
        "sale_id": sales["items"][0]["id"],
    }


async def test_seller_creates_shipment_and_buyer_tracks_it(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)
    base = f"/api/v1/seller/orders/{ctx['sale_id']}/shipment"

    created = await integration_client.post(
        base,
        json={"carrier": "Servientrega", "tracking_number": "GUIA-123", "cost": "8000"},
        headers=_auth(ctx["seller"]),
    )
    assert created.status_code == 201, created.text
    shipment = created.json()
    assert shipment["status"] == "ready"
    assert shipment["carrier"] == "Servientrega"
    assert shipment["tracking_number"] == "GUIA-123"
    assert Decimal(shipment["cost"]) == Decimal("8000.00")
    assert shipment["currency"] == "COP"
    assert [event["status"] for event in shipment["events"]] == ["ready"]

    # El comprador ve el envío de su orden.
    buyer_view = await integration_client.get(
        f"/api/v1/orders/{ctx['order_id']}/shipments", headers=_auth(ctx["buyer"])
    )
    assert buyer_view.status_code == 200
    assert len(buyer_view.json()) == 1
    assert buyer_view.json()[0]["tracking_number"] == "GUIA-123"

    # Otro usuario (sin tienda) no puede verlo.
    other = await _register(integration_client, "other@example.com", "Otro")
    forbidden = await integration_client.get(base, headers=_auth(other))
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "store_required"


async def test_shipment_status_flow_completes_order(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)
    base = f"/api/v1/seller/orders/{ctx['sale_id']}/shipment"
    await integration_client.post(
        base, json={"carrier": "Servientrega"}, headers=_auth(ctx["seller"])
    )

    response = await integration_client.post(base, json={}, headers=_auth(ctx["seller"]))
    assert response.status_code == 409  # no se duplica

    last: Any = None
    for status in ("shipped", "in_transit", "delivered"):
        last = await integration_client.post(
            f"{base}/status", params={"status": status}, headers=_auth(ctx["seller"])
        )
        assert last.status_code == 200, last.text
        assert last.json()["status"] == status

    shipment = last.json()
    assert [event["status"] for event in shipment["events"]] == [
        "ready",
        "shipped",
        "in_transit",
        "delivered",
    ]
    assert shipment["shipped_at"] is not None
    assert shipment["delivered_at"] is not None

    # La sub-orden quedó entregada y la orden completa pasa a `completed`.
    sales = (
        await integration_client.get("/api/v1/seller/orders", headers=_auth(ctx["seller"]))
    ).json()
    assert sales["items"][0]["status"] == "delivered"

    order = (
        await integration_client.get(
            f"/api/v1/orders/{ctx['order_id']}", headers=_auth(ctx["buyer"])
        )
    ).json()
    assert order["status"] == "completed"
    assert order["seller_orders"][0]["status"] == "delivered"


async def test_invalid_shipment_transition(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)
    base = f"/api/v1/seller/orders/{ctx['sale_id']}/shipment"
    await integration_client.post(base, json={}, headers=_auth(ctx["seller"]))

    # No se puede saltar de `ready` a `delivered`.
    skipped = await integration_client.post(
        f"{base}/status", params={"status": "delivered"}, headers=_auth(ctx["seller"])
    )
    assert skipped.status_code == 409
    assert skipped.json()["code"] == "invalid_status_transition"


async def test_shipment_requires_store(integration_client: AsyncClient) -> None:
    token = await _register(integration_client, "nobody@example.com", "Sin tienda")
    resp = await integration_client.post(
        "/api/v1/seller/orders/00000000-0000-0000-0000-000000000000/shipment",
        json={},
        headers=_auth(token),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "store_required"


async def test_update_shipment_keeps_single_record(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _paid_order(integration_client, db_session)
    base = f"/api/v1/seller/orders/{ctx['sale_id']}/shipment"
    first = await integration_client.post(
        base, json={"carrier": "Uno"}, headers=_auth(ctx["seller"])
    )
    assert first.status_code == 201

    again = await integration_client.post(
        base, json={"carrier": "Dos"}, headers=_auth(ctx["seller"])
    )
    assert again.status_code == 409
    assert again.json()["code"] == "shipment_exists"

    updated = await integration_client.patch(
        base, json={"tracking_number": "GUIA-999"}, headers=_auth(ctx["seller"])
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == first.json()["id"]
    assert updated.json()["tracking_number"] == "GUIA-999"
    assert updated.json()["carrier"] == "Uno"
