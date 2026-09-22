"""Pruebas de integración del módulo de órdenes (checkout, idempotencia y ventas)."""

from decimal import Decimal
from typing import Any

from httpx import AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User, UserRole

ADDRESS: dict[str, str] = {
    "recipient": "Juan Perez",
    "phone": "+573001234567",
    "line1": "Calle 123 #45-67",
    "city": "Bogota",
    "country": "CO",
}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


TEST_REDIS_URL = "redis://localhost:6379/1"


async def _reset_register_rate_limit() -> None:
    """Limpia el límite de registro (3/min por IP).

    Las pruebas de checkout crean varios usuarios (admin, vendedores y comprador),
    así que reiniciamos el contador para no topar con el rate limit.
    """
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _login(client: AsyncClient, email: str) -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    return str(login.json()["access_token"])


async def _register(client: AsyncClient, email: str, full_name: str = "Usuario") -> str:
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": full_name},
    )
    assert response.status_code == 201
    return await _login(client, email)


async def _setup_catalog(
    client: AsyncClient, db_session: AsyncSession, commission: str = "12.5"
) -> tuple[str, str]:
    """Crea el admin y una categoría con comisión; devuelve (token_admin, id_categoría)."""
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
            json={"name": "Ropa", "commission_rate": commission},
            headers=_auth(admin_token),
        )
    ).json()
    return admin_token, category["id"]


async def _create_store_with_product(
    client: AsyncClient,
    *,
    seller_email: str,
    admin_token: str,
    category_id: str,
    sku: str,
    price: str = "25000",
    stock: int = 10,
    store_name: str = "Tienda Uno",
) -> dict[str, Any]:
    """Crea vendedor + tienda aprobada + producto; devuelve variante, tienda y token."""
    seller_token = await _register(client, seller_email, "Vendedor")
    store = (
        await client.post(
            "/api/v1/sellers/me", json={"name": store_name}, headers=_auth(seller_token)
        )
    ).json()
    await client.post(f"/api/v1/sellers/{store['id']}/approve", headers=_auth(admin_token))

    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": f"Producto {sku}",
                "category_id": category_id,
                "variants": [{"sku": sku, "price": price, "stock": stock}],
            },
            headers=_auth(seller_token),
        )
    ).json()
    publish = await client.post(
        f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(seller_token)
    )
    assert publish.status_code == 200
    return {
        "variant_id": product["variants"][0]["id"],
        "store_id": store["id"],
        "token": seller_token,
    }


async def _add_to_cart(client: AsyncClient, token: str, variant_id: str, quantity: int) -> None:
    resp = await client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": quantity},
        headers=_auth(token),
    )
    assert resp.status_code == 200


async def _checkout(client: AsyncClient, token: str, *, key: str | None = None) -> Response:
    headers = _auth(token)
    if key is not None:
        headers["Idempotency-Key"] = key
    return await client.post(
        "/api/v1/orders",
        json={"shipping_address": ADDRESS, "notes": "Entregar en la tarde"},
        headers=headers,
    )


async def test_checkout_creates_order_and_reserves_stock(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token, category_id = await _setup_catalog(integration_client, db_session)
    seller = await _create_store_with_product(
        integration_client,
        seller_email="seller@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-O1",
        stock=10,
    )
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")
    await _add_to_cart(integration_client, buyer_token, seller["variant_id"], 2)

    resp = await _checkout(integration_client, buyer_token)
    assert resp.status_code == 201
    order = resp.json()

    assert order["order_number"].startswith("ORD-")
    assert order["status"] == "pending"
    assert order["payment_status"] == "pending"
    assert order["currency"] == "COP"
    assert Decimal(order["subtotal"]) == Decimal("50000.00")
    assert Decimal(order["total"]) == Decimal("50000.00")
    assert order["shipping_address"]["city"] == "Bogota"

    assert len(order["seller_orders"]) == 1
    sale = order["seller_orders"][0]
    assert sale["store_id"] == seller["store_id"]
    assert sale["status"] == "pending"
    assert Decimal(sale["subtotal"]) == Decimal("50000.00")
    assert Decimal(sale["commission_amount"]) == Decimal("6250.00")  # 12,5 %
    assert Decimal(sale["payout_amount"]) == Decimal("43750.00")

    assert len(sale["items"]) == 1
    item = sale["items"][0]
    assert item["sku"] == "SKU-O1"
    assert item["product_title"] == "Producto SKU-O1"
    assert Decimal(item["unit_price"]) == Decimal("25000.00")
    assert item["quantity"] == 2
    assert Decimal(item["line_total"]) == Decimal("50000.00")
    assert Decimal(item["commission_rate"]) == Decimal("12.5")

    # El carrito queda vacío y el stock reservado.
    cart = await integration_client.get("/api/v1/cart", headers=_auth(buyer_token))
    assert cart.json()["items"] == []

    inventory = await integration_client.get(f"/api/v1/inventory/items/{seller['variant_id']}")
    assert inventory.json()["reserved_quantity"] == 2
    assert inventory.json()["available"] == 8

    listing = await integration_client.get("/api/v1/orders", headers=_auth(buyer_token))
    assert listing.json()["items"][0]["order_number"] == order["order_number"]


async def test_checkout_requires_items(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _setup_catalog(integration_client, db_session)
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")

    resp = await _checkout(integration_client, buyer_token)
    assert resp.status_code == 400
    assert resp.json()["code"] == "cart_empty"


async def test_checkout_rolls_back_when_stock_is_missing(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token, category_id = await _setup_catalog(integration_client, db_session)
    seller = await _create_store_with_product(
        integration_client,
        seller_email="seller@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-O3",
        stock=3,
    )
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")
    await _add_to_cart(integration_client, buyer_token, seller["variant_id"], 5)

    resp = await _checkout(integration_client, buyer_token)
    assert resp.status_code == 409
    assert resp.json()["code"] == "insufficient_stock"

    # Nada se aplicó: ni orden, ni reserva, y el carrito sigue intacto.
    listing = await integration_client.get("/api/v1/orders", headers=_auth(buyer_token))
    assert listing.json()["items"] == []

    inventory = await integration_client.get(f"/api/v1/inventory/items/{seller['variant_id']}")
    assert inventory.json()["reserved_quantity"] == 0
    assert inventory.json()["available"] == 3

    cart = await integration_client.get("/api/v1/cart", headers=_auth(buyer_token))
    assert cart.json()["total_items"] == 5


async def test_checkout_is_idempotent(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token, category_id = await _setup_catalog(integration_client, db_session)
    seller = await _create_store_with_product(
        integration_client,
        seller_email="seller@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-O4",
        stock=10,
    )
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")
    await _add_to_cart(integration_client, buyer_token, seller["variant_id"], 1)

    first = await _checkout(integration_client, buyer_token, key="checkout-123")
    second = await _checkout(integration_client, buyer_token, key="checkout-123")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["order_number"] == second.json()["order_number"]

    listing = await integration_client.get("/api/v1/orders", headers=_auth(buyer_token))
    assert len(listing.json()["items"]) == 1

    inventory = await integration_client.get(f"/api/v1/inventory/items/{seller['variant_id']}")
    assert inventory.json()["reserved_quantity"] == 1


async def test_cancel_releases_stock(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token, category_id = await _setup_catalog(integration_client, db_session)
    seller = await _create_store_with_product(
        integration_client,
        seller_email="seller@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-O5",
        stock=10,
    )
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")
    await _add_to_cart(integration_client, buyer_token, seller["variant_id"], 3)
    order = (await _checkout(integration_client, buyer_token)).json()

    cancelled = await integration_client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=_auth(buyer_token)
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["seller_orders"][0]["status"] == "cancelled"

    inventory = await integration_client.get(f"/api/v1/inventory/items/{seller['variant_id']}")
    assert inventory.json()["reserved_quantity"] == 0
    assert inventory.json()["available"] == 10

    again = await integration_client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=_auth(buyer_token)
    )
    assert again.status_code == 409
    assert again.json()["code"] == "order_not_cancellable"


async def test_order_splits_by_store(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token, category_id = await _setup_catalog(integration_client, db_session)
    first = await _create_store_with_product(
        integration_client,
        seller_email="seller1@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-A",
        price="10000",
        stock=5,
        store_name="Tienda A",
    )
    second = await _create_store_with_product(
        integration_client,
        seller_email="seller2@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-B",
        price="20000",
        stock=5,
        store_name="Tienda B",
    )
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")
    await _add_to_cart(integration_client, buyer_token, first["variant_id"], 2)
    await _add_to_cart(integration_client, buyer_token, second["variant_id"], 1)

    order = (await _checkout(integration_client, buyer_token)).json()
    assert len(order["seller_orders"]) == 2
    assert Decimal(order["subtotal"]) == Decimal("40000.00")

    by_store = {sale["store_id"]: sale for sale in order["seller_orders"]}
    assert Decimal(by_store[first["store_id"]]["subtotal"]) == Decimal("20000.00")
    assert Decimal(by_store[second["store_id"]]["subtotal"]) == Decimal("20000.00")
    assert Decimal(by_store[first["store_id"]]["commission_amount"]) == Decimal("2500.00")


async def test_seller_lists_sales_and_updates_status(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_token, category_id = await _setup_catalog(integration_client, db_session)
    seller = await _create_store_with_product(
        integration_client,
        seller_email="seller@example.com",
        admin_token=admin_token,
        category_id=category_id,
        sku="SKU-O7",
        stock=10,
    )
    buyer_token = await _register(integration_client, "buyer@example.com", "Comprador")
    await _add_to_cart(integration_client, buyer_token, seller["variant_id"], 1)
    await _checkout(integration_client, buyer_token)

    sales = await integration_client.get("/api/v1/seller/orders", headers=_auth(seller["token"]))
    assert sales.status_code == 200
    body = sales.json()
    assert len(body["items"]) == 1
    sale_id = body["items"][0]["id"]
    assert Decimal(body["items"][0]["payout_amount"]) == Decimal("21875.00")

    # No se puede saltar de `pending` a `shipped`.
    skipped = await integration_client.patch(
        f"/api/v1/seller/orders/{sale_id}/status",
        params={"status": "shipped"},
        headers=_auth(seller["token"]),
    )
    assert skipped.status_code == 409
    assert skipped.json()["code"] == "invalid_status_transition"

    processing = await integration_client.patch(
        f"/api/v1/seller/orders/{sale_id}/status",
        params={"status": "processing"},
        headers=_auth(seller["token"]),
    )
    assert processing.status_code == 200
    assert processing.json()["status"] == "processing"
    assert len(processing.json()["items"]) == 1


async def test_seller_sales_require_a_store(integration_client: AsyncClient) -> None:
    token = await _register(integration_client, "nobody@example.com", "Sin tienda")
    resp = await integration_client.get("/api/v1/seller/orders", headers=_auth(token))
    assert resp.status_code == 403
    assert resp.json()["code"] == "store_required"
