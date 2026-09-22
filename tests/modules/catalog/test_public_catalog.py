"""Pruebas de lo que la API enseña en público: stock y atributos de las variantes, tienda y envío.

Son las tres cosas que bloqueaban la ficha de producto y el checkout del frontend (apartados 10
y 11 de `docs/PENDIENTES-BACKEND.md`).
"""

import uuid
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Attribute, AttributeType, CategoryAttribute
from app.modules.inventory.service import InventoryService
from tests.modules.catalog.test_products import _auth, _create_category, _login, _setup_seller


async def _create_product_with_attribute(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[dict[str, Any], uuid.UUID, str]:
    """Categoría + atributo «Talla» + producto con una variante «M».

    Devuelve `(producto, attribute_id, token)`. El atributo y su vínculo con la categoría se crean
    directamente en la base de datos: lo que se prueba aquí es la **lectura pública**, no el alta
    de atributos (que ya tiene sus pruebas en `test_catalog.py`).
    """
    token = await _setup_seller(client, db_session)
    category = await _create_category(client, db_session)

    attribute = Attribute(name="Talla", type=AttributeType.SELECT)
    db_session.add(attribute)
    await db_session.flush()
    db_session.add(
        CategoryAttribute(
            category_id=uuid.UUID(category["id"]), attribute_id=attribute.id, is_required=True
        )
    )
    await db_session.commit()

    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": "Camiseta",
                "category_id": category["id"],
                "variants": [
                    {
                        "sku": "CAM-M",
                        "price": "25000",
                        "stock": 7,
                        "attribute_values": [{"attribute_id": str(attribute.id), "value": "M"}],
                    }
                ],
            },
            headers=_auth(token),
        )
    ).json()

    return product, attribute.id, token


async def test_public_product_shows_stock_and_attribute_values(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`VariantOut` trae stock, disponible y los valores de atributo; `ProductOut` trae el total."""
    product, attribute_id, _ = await _create_product_with_attribute(integration_client, db_session)
    variant = product["variants"][0]

    # La respuesta del alta ya trae los campos nuevos: stock sembrado y el atributo recién creado.
    assert variant["stock"] == 7
    assert variant["available"] == 7
    assert variant["attribute_values"] == [
        {"attribute_id": str(attribute_id), "name": "Talla", "value": "M"}
    ]

    # Se reserva una unidad para comprobar que `available` descuenta lo reservado (y `stock` no).
    await InventoryService(db_session).reserve(uuid.UUID(variant["id"]), 1)

    response = await integration_client.get(f"/api/v1/catalog/products/{product['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["variants"][0]["stock"] == 7
    assert body["variants"][0]["available"] == 6
    assert body["total_available"] == 6


async def test_shipping_estimate_is_public_and_declares_its_source(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """La estimación de entrega es pública, está ordenada y dice de dónde sale."""
    product, _, _ = await _create_product_with_attribute(integration_client, db_session)

    local = await integration_client.get(f"/api/v1/catalog/products/{product['id']}/shipping")
    assert local.status_code == 200
    body = local.json()
    assert body["source"] == "configured_default"
    # El coste es 0 porque el envío del comprador se define en el checkout (decisión 0012); la
    # estimación la declara la propia respuesta con `source`.
    assert Decimal(body["shipping_cost"]) == Decimal("0")
    assert body["estimated_delivery_min"] <= body["estimated_delivery_max"]

    international = await integration_client.get(
        f"/api/v1/catalog/products/{product['id']}/shipping", params={"country": "US"}
    )
    assert international.status_code == 200
    assert international.json()["destination_country"] == "US"
    assert international.json()["transit_days_max"] > body["transit_days_max"], (
        "un envío internacional no puede ser más rápido que uno local"
    )

    missing = await integration_client.get(f"/api/v1/catalog/products/{uuid.uuid4()}/shipping")
    assert missing.status_code == 404

    invalid_country = await integration_client.get(
        f"/api/v1/catalog/products/{product['id']}/shipping", params={"country": "COLOMBIA"}
    )
    assert invalid_country.status_code == 422


async def test_public_store_shows_reputation_and_hides_internal_data(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """La tienda pública devuelve reputación y pedidos entregados, sin datos internos."""
    token = await _setup_seller(integration_client, db_session)
    store = (await integration_client.get("/api/v1/sellers/me", headers=_auth(token))).json()

    response = await integration_client.get(f"/api/v1/stores/{store['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Tienda"
    assert body["orders_delivered"] == 0
    assert body["rating_count"] == 0
    assert "user_id" not in body
    assert "status" not in body


async def test_public_store_hides_unapproved_stores(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Una tienda sin aprobar no existe para el público (404, sin revelar su estado)."""
    await integration_client.post(
        "/api/v1/auth/register",
        json={"email": "pending@example.com", "password": "secret123", "full_name": "Pending"},
    )
    pending_token = await _login(integration_client, "pending@example.com")
    store = (
        await integration_client.post(
            "/api/v1/sellers/me", json={"name": "Tienda pendiente"}, headers=_auth(pending_token)
        )
    ).json()

    response = await integration_client.get(f"/api/v1/stores/{store['id']}")

    assert response.status_code == 404
    assert response.json()["code"] == "store_not_found"


async def test_public_product_by_slug(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`GET /catalog/products/by-slug/{slug}` devuelve lo mismo que la consulta por id."""
    product, _, _ = await _create_product_with_attribute(integration_client, db_session)

    by_slug = await integration_client.get(
        f"/api/v1/catalog/products/by-slug/{product['slug']}"
    )
    assert by_slug.status_code == 200, by_slug.text
    body = by_slug.json()
    assert body["id"] == product["id"]
    assert body["slug"] == product["slug"]
    assert body["variants"][0]["sku"] == "CAM-M"
    assert body["variants"][0]["stock"] == 7

    missing = await integration_client.get("/api/v1/catalog/products/by-slug/no-existe")
    assert missing.status_code == 404
    assert missing.json()["code"] == "product_not_found"


async def test_public_product_listing_walks_the_catalog_for_the_sitemap(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`GET /catalog/products/public` recorre el catálogo publicado por cursor (apartado 13).

    Trae `slug` y `updated_at` (el `lastmod` del sitemap), solo productos activos y sin repetir ni
    perder filas entre páginas.
    """
    token = await _setup_seller(integration_client, db_session)
    category = await _create_category(integration_client, db_session)

    published: list[str] = []
    for index, title in enumerate(["Camiseta", "Pantalon", "Zapatos"]):
        product = (
            await integration_client.post(
                "/api/v1/catalog/products",
                json={
                    "title": title,
                    "category_id": category["id"],
                    "variants": [{"sku": f"SKU-{index}", "price": "25000", "stock": 3}],
                },
                headers=_auth(token),
            )
        ).json()
        await integration_client.post(
            f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(token)
        )
        published.append(product["slug"])

    # Un borrador no es una URL pública, así que no sale en el listado.
    draft = (
        await integration_client.post(
            "/api/v1/catalog/products",
            json={
                "title": "Sin publicar",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-DRAFT", "price": "1000", "stock": 1}],
            },
            headers=_auth(token),
        )
    ).json()

    # Página 1: máximo 2 y con cursor, porque quedan más.
    first = await integration_client.get(
        "/api/v1/catalog/products/public", params={"limit": 2}
    )
    assert first.status_code == 200, first.text
    page_one = first.json()
    assert len(page_one["items"]) == 2
    assert page_one["next_cursor"]
    assert set(page_one["items"][0]) == {"id", "slug", "title", "updated_at"}

    # Página 2: el resto, sin repetir nada.
    second = await integration_client.get(
        "/api/v1/catalog/products/public",
        params={"limit": 2, "cursor": page_one["next_cursor"]},
    )
    page_two = second.json()
    assert len(page_two["items"]) == 1
    assert page_two["next_cursor"] is None

    slugs = [item["slug"] for item in page_one["items"] + page_two["items"]]
    assert sorted(slugs) == sorted(published)
    assert draft["slug"] not in slugs
    assert all(item["updated_at"] for item in page_one["items"] + page_two["items"])

    # El filtro `q` sirve para trocear el sitemap por partes.
    filtered = await integration_client.get(
        "/api/v1/catalog/products/public", params={"q": "pantalon"}
    )
    assert [item["slug"] for item in filtered.json()["items"]] == ["pantalon"]

    # Un cursor corrupto se rechaza con el código estable de siempre.
    broken = await integration_client.get(
        "/api/v1/catalog/products/public", params={"cursor": "no-es-un-cursor"}
    )
    assert broken.status_code == 400
    assert broken.json()["code"] == "invalid_cursor"

