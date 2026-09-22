"""Pruebas de integración del cambio de stock de una variante por su vendedor (F8).

El stock solo se podía fijar al crear la variante (`/inventory/items/{id}/adjust` es solo de
administración y `ProductUpdate` no acepta variantes), así que el panel del vendedor lo mostraba
en solo lectura. `PATCH /catalog/products/{id}/variants/{id}/stock` cierra esa laguna; aquí se
prueba lo que importa: que el dueño puede, que **nadie más** puede (otro vendedor o un comprador
reciben 403) y que el inventario no se puede dejar por debajo de lo ya reservado.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User
from app.modules.inventory.models import InventoryMovement
from app.modules.sellers.models import Store, StoreStatus
from tests.modules.catalog.test_products import _auth, _create_category, _login, _setup_seller

TEST_REDIS_URL = "redis://localhost:6379/1"


async def _reset_auth_rate_limits() -> None:
    """Registro (3/min) y login (5/min) van por IP y aquí se crean varios usuarios."""
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        keys += await redis.keys("rate_limit:login:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _register(client: AsyncClient, email: str) -> str:
    """Registra e inicia sesión; devuelve el access token."""
    await _reset_auth_rate_limits()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": "Usuario"},
    )
    assert response.status_code == 201, response.text
    return await _login(client, email)


async def _approve_store_in_db(db_session: AsyncSession, email: str) -> None:
    """Crea la tienda aprobada directamente en la base (ahorra un login de administrador)."""
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    db_session.add(
        Store(
            user_id=user.id,
            name=f"Tienda {email}",
            slug=f"tienda-{email.split('@')[0]}",
            status=StoreStatus.APPROVED,
        )
    )
    await db_session.commit()


async def _setup_product(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Vendedor con tienda aprobada + producto con una variante de 10 unidades."""
    seller_token = await _setup_seller(client, db_session)
    category = await _create_category(client, db_session)

    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": "Camiseta",
                "category_id": category["id"],
                "variants": [{"sku": "CAM-M", "price": "25000", "stock": 10}],
            },
            headers=_auth(seller_token),
        )
    ).json()
    return {
        "seller": seller_token,
        "product_id": product["id"],
        "variant_id": product["variants"][0]["id"],
    }


def _stock_url(ctx: dict[str, Any], variant_id: str | None = None) -> str:
    variant = variant_id or ctx["variant_id"]
    return f"/api/v1/catalog/products/{ctx['product_id']}/variants/{variant}/stock"


async def _movements(db_session: AsyncSession, variant_id: str) -> list[tuple[int, str]]:
    """Movimientos del ledger de la variante, del más antiguo al más reciente."""
    rows = (
        (
            await db_session.execute(
                select(InventoryMovement)
                .where(InventoryMovement.variant_id == uuid.UUID(variant_id))
                .order_by(InventoryMovement.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [(movement.delta, movement.reason) for movement in rows]


async def test_owner_can_change_variant_stock(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup_product(integration_client, db_session)

    response = await integration_client.patch(
        _stock_url(ctx), json={"stock": 3}, headers=_auth(ctx["seller"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["variants"][0]["stock"] == 3
    assert body["variants"][0]["available"] == 3
    assert body["total_available"] == 3

    # El delta (-7 partiendo de 10) lo calcula el servidor y queda en el ledger de inventario.
    assert await _movements(db_session, ctx["variant_id"]) == [
        (10, "initial"),
        (-7, "seller_update"),
    ]

    # Repetir el mismo valor no ensucia el ledger (delta 0).
    again = await integration_client.patch(
        _stock_url(ctx), json={"stock": 3}, headers=_auth(ctx["seller"])
    )
    assert again.status_code == 200
    assert len(await _movements(db_session, ctx["variant_id"])) == 2


async def test_other_seller_and_buyer_cannot_change_stock(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup_product(integration_client, db_session)

    # Otro vendedor con tienda aprobada: el producto no es suyo.
    other_token = await _register(integration_client, "otro@example.com")
    await _approve_store_in_db(db_session, "otro@example.com")
    forbidden = await integration_client.patch(
        _stock_url(ctx), json={"stock": 99}, headers=_auth(other_token)
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "forbidden"

    # Comprador sin tienda: ni siquiera puede llegar al catálogo del vendedor.
    buyer_token = await _register(integration_client, "buyer@example.com")
    no_store = await integration_client.patch(
        _stock_url(ctx), json={"stock": 99}, headers=_auth(buyer_token)
    )
    assert no_store.status_code == 403
    assert no_store.json()["code"] == "seller_required"

    # Sin sesión.
    anonymous = await integration_client.patch(_stock_url(ctx), json={"stock": 99})
    assert anonymous.status_code == 401

    # Ningún intento movió el stock.
    product = (await integration_client.get(f"/api/v1/catalog/products/{ctx['product_id']}")).json()
    assert product["variants"][0]["stock"] == 10


async def test_stock_cannot_go_below_reserved(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup_product(integration_client, db_session)
    admin_token = await _login(integration_client, "admin@example.com")

    # Cuatro unidades reservadas por una orden en curso (endpoint de administración).
    reserved = await integration_client.post(
        f"/api/v1/inventory/items/{ctx['variant_id']}/reserve",
        json={"quantity": 4},
        headers=_auth(admin_token),
    )
    assert reserved.status_code == 200, reserved.text

    too_low = await integration_client.patch(
        _stock_url(ctx), json={"stock": 2}, headers=_auth(ctx["seller"])
    )
    assert too_low.status_code == 409
    assert too_low.json()["code"] == "insufficient_stock"

    # Justo hasta lo reservado sí: quedan 0 disponibles, pero no se pierde lo vendido.
    exactly = await integration_client.patch(
        _stock_url(ctx), json={"stock": 4}, headers=_auth(ctx["seller"])
    )
    assert exactly.status_code == 200
    assert exactly.json()["variants"][0]["available"] == 0

    negative = await integration_client.patch(
        _stock_url(ctx), json={"stock": -1}, headers=_auth(ctx["seller"])
    )
    assert negative.status_code == 422


async def test_unknown_variant_or_product_returns_404(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup_product(integration_client, db_session)

    missing_variant = await integration_client.patch(
        _stock_url(ctx, str(uuid.uuid4())), json={"stock": 5}, headers=_auth(ctx["seller"])
    )
    assert missing_variant.status_code == 404
    assert missing_variant.json()["code"] == "variant_not_found"

    missing_product = await integration_client.patch(
        f"/api/v1/catalog/products/{uuid.uuid4()}/variants/{ctx['variant_id']}/stock",
        json={"stock": 5},
        headers=_auth(ctx["seller"]),
    )
    assert missing_product.status_code == 404
    assert missing_product.json()["code"] == "product_not_found"
