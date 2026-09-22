"""Pruebas de integración del módulo de carrito (invitados, usuarios y fusión)."""

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import (
    Attribute,
    AttributeType,
    ProductImage,
    ProductVariant,
    VariantValue,
)
from app.modules.identity.models import User, UserRole


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, email: str) -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})
    return str(login.json()["access_token"])


async def _setup_product(
    client: AsyncClient,
    db_session: AsyncSession,
    sku: str,
    price: str = "25000",
    stock: int = 50,
) -> str:
    """Crea vendedor + tienda aprobada + categoría + producto y devuelve la variante."""
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

    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": f"Producto {sku}",
                "category_id": category["id"],
                "variants": [{"sku": sku, "price": price, "stock": stock}],
            },
            headers=_auth(seller_token),
        )
    ).json()
    return str(product["variants"][0]["id"])


async def _register_customer(client: AsyncClient) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "buyer@example.com", "password": "secret123", "full_name": "Buyer"},
    )
    return await _login(client, "buyer@example.com")


async def test_guest_cart_flow(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    variant_id = await _setup_product(integration_client, db_session, "SKU-CART-1")

    # El primer GET genera un token de carrito para el invitado.
    empty = await integration_client.get("/api/v1/cart")
    assert empty.status_code == 200
    guest_token = empty.headers.get("X-Cart-Token")
    assert guest_token
    assert empty.json()["items"] == []
    assert empty.json()["subtotal"] == "0.00"

    guest_headers = {"X-Cart-Token": guest_token}
    added = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 2},
        headers=guest_headers,
    )
    assert added.status_code == 200
    body = added.json()
    assert body["total_items"] == 2
    assert Decimal(body["subtotal"]) == Decimal("50000.00")
    assert body["currency"] == "COP"
    assert body["items"][0]["variant_id"] == variant_id

    # Añadir la misma variante incrementa la cantidad.
    again = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 1},
        headers=guest_headers,
    )
    assert again.json()["total_items"] == 3

    updated = await integration_client.patch(
        f"/api/v1/cart/items/{variant_id}", json={"quantity": 5}, headers=guest_headers
    )
    assert updated.status_code == 200
    assert Decimal(updated.json()["subtotal"]) == Decimal("125000.00")

    removed = await integration_client.delete(
        f"/api/v1/cart/items/{variant_id}", headers=guest_headers
    )
    assert removed.status_code == 200
    assert removed.json()["items"] == []


async def test_authenticated_cart_flow(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    variant_id = await _setup_product(integration_client, db_session, "SKU-CART-2")
    token = await _register_customer(integration_client)

    added = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 3},
        headers=_auth(token),
    )
    assert added.status_code == 200
    assert added.json()["total_items"] == 3
    assert not added.headers.get("X-Cart-Token")

    cart = await integration_client.get("/api/v1/cart", headers=_auth(token))
    assert cart.status_code == 200
    assert Decimal(cart.json()["subtotal"]) == Decimal("75000.00")

    cleared = await integration_client.delete("/api/v1/cart", headers=_auth(token))
    assert cleared.status_code == 200
    assert cleared.json()["items"] == []
    assert cleared.json()["total_items"] == 0


async def test_merge_guest_cart_into_user(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    variant_id = await _setup_product(integration_client, db_session, "SKU-CART-3")

    empty = await integration_client.get("/api/v1/cart")
    guest_token = str(empty.headers["X-Cart-Token"])
    await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 2},
        headers={"X-Cart-Token": guest_token},
    )

    token = await _register_customer(integration_client)
    merged = await integration_client.post(
        "/api/v1/cart/merge",
        headers={**_auth(token), "X-Cart-Token": guest_token},
    )
    assert merged.status_code == 200
    assert merged.json()["total_items"] == 2

    # Tras la fusión el carrito de invitado queda vacío.
    guest_cart = await integration_client.get(
        "/api/v1/cart", headers={"X-Cart-Token": guest_token}
    )
    assert guest_cart.json()["items"] == []


async def test_cart_line_reports_stock_thumbnail_attributes_and_price_change(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """La línea trae lo que la interfaz necesita: stock, imagen, atributos y aviso de precio."""
    variant_id = await _setup_product(
        integration_client, db_session, "SKU-CART-STOCK", "25000", stock=2
    )

    # Imagen y atributo de la variante: se insertan directamente porque lo que se prueba es lo que
    # devuelve el carrito (subir la imagen necesita MinIO y es otra prueba).
    variant = (
        await db_session.execute(
            select(ProductVariant).where(ProductVariant.id == uuid.UUID(variant_id))
        )
    ).scalar_one()
    attribute = Attribute(name="Talla", type=AttributeType.TEXT)
    db_session.add(attribute)
    await db_session.flush()
    db_session.add(
        ProductImage(product_id=variant.product_id, object_key="products/abc123.png", position=0)
    )
    db_session.add(VariantValue(variant_id=variant.id, attribute_id=attribute.id, value="M"))
    await db_session.commit()

    buyer = await _register_customer(integration_client)
    added = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 2},
        headers=_auth(buyer),
    )
    assert added.status_code == 200, added.text
    line = added.json()["items"][0]
    assert line["available"] == 2
    assert Decimal(str(line["added_unit_price"])) == Decimal("25000.00")
    assert line["price_changed"] is False
    assert line["thumbnail"] == "products/abc123.png"
    assert line["attribute_values"] == [
        {"attribute_id": str(attribute.id), "name": "Talla", "value": "M"}
    ]

    # El vendedor sube el precio después de añadirlo al carrito: la línea lo avisa y conserva el
    # precio con el que se añadió.
    variant.price = Decimal("29000")
    await db_session.commit()

    after = await integration_client.get("/api/v1/cart", headers=_auth(buyer))
    line = after.json()["items"][0]
    assert line["price_changed"] is True
    assert Decimal(str(line["added_unit_price"])) == Decimal("25000.00")
    assert Decimal(str(line["unit_price"])) == Decimal("29000.00")


async def test_cart_rejects_more_than_available(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """No se puede dejar en el carrito más de lo disponible (ni sumando ni fijando la cantidad)."""
    variant_id = await _setup_product(integration_client, db_session, "SKU-CART-LIMIT", stock=2)
    buyer = await _register_customer(integration_client)

    too_many = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 3},
        headers=_auth(buyer),
    )
    assert too_many.status_code == 409
    assert too_many.json()["code"] == "insufficient_stock"

    ok = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 2},
        headers=_auth(buyer),
    )
    assert ok.status_code == 200, ok.text

    extra = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 1},
        headers=_auth(buyer),
    )
    assert extra.status_code == 409
    assert extra.json()["code"] == "insufficient_stock"

    patched = await integration_client.patch(
        f"/api/v1/cart/items/{variant_id}", json={"quantity": 5}, headers=_auth(buyer)
    )
    assert patched.status_code == 409
    assert patched.json()["code"] == "insufficient_stock"

    # El invitado también lo comprueba (su carrito se valida contra el mismo inventario).
    guest = await integration_client.post(
        "/api/v1/cart/items", json={"variant_id": variant_id, "quantity": 3}
    )
    assert guest.status_code == 409
    assert guest.json()["code"] == "insufficient_stock"


async def test_quantity_limit_exceeded(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Con stock de sobra, el límite que salta es el de 100 unidades por línea del carrito.
    variant_id = await _setup_product(integration_client, db_session, "SKU-CART-4", stock=200)
    token = await _register_customer(integration_client)

    first = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 60},
        headers=_auth(token),
    )
    assert first.status_code == 200

    exceeded = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": variant_id, "quantity": 60},
        headers=_auth(token),
    )
    assert exceeded.status_code == 400
    assert exceeded.json()["code"] == "quantity_limit_exceeded"


async def test_add_unknown_variant(integration_client: AsyncClient) -> None:
    resp = await integration_client.post(
        "/api/v1/cart/items",
        json={"variant_id": "00000000-0000-0000-0000-000000000000", "quantity": 1},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "variant_not_found"
