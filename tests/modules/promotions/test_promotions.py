"""Pruebas de integración del módulo de promociones (cupones)."""

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
    client: AsyncClient, db_session: AsyncSession, *, price: str = "25000", quantity: int = 1
) -> dict[str, Any]:
    """Admin + tienda + producto publicado + comprador con unidades en el carrito."""
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
                "title": "Producto Cupon",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-CPN", "price": price, "stock": 20}],
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
        json={"variant_id": product["variants"][0]["id"], "quantity": quantity},
        headers=_auth(buyer_token),
    )
    return {
        "admin": admin_token,
        "buyer": buyer_token,
        "seller": seller_token,
        "product_id": product["id"],
        "variant_id": product["variants"][0]["id"],
    }


async def _create_coupon(client: AsyncClient, admin_token: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": "DESCUENTO10",
        "discount_type": "percent",
        "value": "10",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/coupons", json=payload, headers=_auth(admin_token))
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _checkout(client: AsyncClient, token: str, coupon: str | None = None) -> Any:
    body: dict[str, Any] = {"shipping_address": ADDRESS}
    if coupon is not None:
        body["coupon_code"] = coupon
    return await client.post("/api/v1/orders", json=body, headers=_auth(token))


async def test_create_coupon_requires_admin(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)
    forbidden = await integration_client.post(
        "/api/v1/coupons",
        json={"code": "NOADMIN", "discount_type": "percent", "value": "10"},
        headers=_auth(ctx["buyer"]),
    )
    assert forbidden.status_code == 403

    coupon = await _create_coupon(integration_client, ctx["admin"])
    assert coupon["code"] == "DESCUENTO10"
    assert coupon["currency"] == "COP"
    assert coupon["used_count"] == 0

    # Código duplicado -> 409.
    duplicated = await integration_client.post(
        "/api/v1/coupons",
        json={"code": "descuento10", "discount_type": "percent", "value": "5"},
        headers=_auth(ctx["admin"]),
    )
    assert duplicated.status_code == 409
    assert duplicated.json()["code"] == "coupon_exists"

    # Vista previa sobre el carrito (25.000): 10% -> 2.500.
    preview = await integration_client.post(
        "/api/v1/coupons/validate",
        json={"code": "descuento10"},
        headers=_auth(ctx["buyer"]),
    )
    assert preview.status_code == 200, preview.text
    assert Decimal(preview.json()["discount_amount"]) == Decimal("2500.00")
    assert Decimal(preview.json()["total"]) == Decimal("22500.00")


async def test_checkout_applies_coupon(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _context(integration_client, db_session)
    await _create_coupon(integration_client, ctx["admin"])

    order = await _checkout(integration_client, ctx["buyer"], coupon="DESCUENTO10")
    assert order.status_code == 201, order.text
    body = order.json()

    assert Decimal(body["subtotal"]) == Decimal("25000.00")
    assert Decimal(body["discount_total"]) == Decimal("2500.00")
    assert Decimal(body["total"]) == Decimal("22500.00")

    sale = body["seller_orders"][0]
    assert Decimal(sale["discount_amount"]) == Decimal("2500.00")
    # 10% de comisión sobre el neto (22.500) = 2.250; liquidación = 25.000 - 2.500 - 2.250.
    assert Decimal(sale["commission_amount"]) == Decimal("2250.00")
    assert Decimal(sale["payout_amount"]) == Decimal("20250.00")

    # El cupón quedó consumido una vez.
    coupons = (await integration_client.get("/api/v1/coupons", headers=_auth(ctx["admin"]))).json()[
        "items"
    ]
    assert coupons[0]["used_count"] == 1


async def test_coupon_rules(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _context(integration_client, db_session)

    unknown = await _checkout(integration_client, ctx["buyer"], coupon="NOEXISTE")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "coupon_not_found"

    await _create_coupon(integration_client, ctx["admin"], min_purchase="50000")
    too_cheap = await _checkout(integration_client, ctx["buyer"], coupon="DESCUENTO10")
    assert too_cheap.status_code == 409
    assert too_cheap.json()["code"] == "min_purchase_not_met"

    expired = await _create_coupon(
        integration_client,
        ctx["admin"],
        code="VIEJO",
        ends_at="2020-01-01T00:00:00Z",
    )
    assert expired["code"] == "VIEJO"
    late = await _checkout(integration_client, ctx["buyer"], coupon="VIEJO")
    assert late.status_code == 409
    assert late.json()["code"] == "coupon_expired"


async def test_coupon_user_limit(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    ctx = await _context(integration_client, db_session)
    await _create_coupon(integration_client, ctx["admin"], max_uses_per_user=1)

    first = await _checkout(integration_client, ctx["buyer"], coupon="DESCUENTO10")
    assert first.status_code == 201

    # Segunda compra del mismo usuario con el mismo cupón -> 409.
    await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": ctx["variant_id"], "quantity": 1},
        headers=_auth(ctx["buyer"]),
    )
    second = await _checkout(integration_client, ctx["buyer"], coupon="DESCUENTO10")
    assert second.status_code == 409
    assert second.json()["code"] == "coupon_user_limit"
