"""Pruebas del interruptor `REQUIRE_VERIFIED_EMAIL` (apartado 6, decisión 0023).

Por defecto está **apagado**: el correo de verificación se envía y se puede canjear, pero ni vender
ni publicar quedan bloqueados (es lo que hace cómodo probar la tienda sin abrir Mailpit). Al
encenderlo, solo hace falta el correo verificado para vender y para publicar preguntas y reseñas.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.identity.models import User
from tests.modules.catalog.test_products import _auth, _create_category, _login, _setup_seller

TEST_REDIS_URL = "redis://localhost:6379/1"


async def _reset_register_rate_limit() -> None:
    """El registro está limitado a 3/min por IP y aquí se crean varios usuarios."""
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _register(client: AsyncClient, email: str, full_name: str = "Usuario") -> None:
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": full_name},
    )
    assert response.status_code == 201, response.text


async def _verify_in_db(db_session: AsyncSession, email: str) -> None:
    """Marca el correo como verificado (canjear el token ya tiene sus pruebas)."""
    result = await db_session.execute(select(User).where(User.email == email))
    result.scalar_one().email_verified_at = datetime.now(UTC)
    await db_session.commit()


async def _publish_product(client: AsyncClient, token: str, category_id: str) -> str:
    """Producto publicado; devuelve su id."""
    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": "Camiseta",
                "category_id": category_id,
                "variants": [{"sku": "CAM-M", "price": "25000", "stock": 5}],
            },
            headers=_auth(token),
        )
    ).json()
    await client.post(f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(token))
    return str(product["id"])


async def test_email_verification_is_not_required_by_default(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Con el interruptor apagado, un correo sin verificar no bloquea nada."""
    assert settings.REQUIRE_VERIFIED_EMAIL is False

    seller_token = await _setup_seller(integration_client, db_session)
    category = await _create_category(integration_client, db_session)
    product_id = await _publish_product(integration_client, seller_token, category["id"])

    # Vendió (tiene tienda aprobada y productos publicados) sin verificar el correo.
    store = await integration_client.get("/api/v1/sellers/me", headers=_auth(seller_token))
    assert store.status_code == 200

    # Y un comprador sin verificar puede preguntar.
    await _register(integration_client, "buyer@example.com", "Buyer")
    buyer_token = await _login(integration_client, "buyer@example.com")
    asked = await integration_client.post(
        f"/api/v1/products/{product_id}/questions",
        json={"body": "¿Tiene garantía?"},
        headers=_auth(buyer_token),
    )
    assert asked.status_code == 201, asked.text


async def test_require_verified_email_blocks_selling_and_publishing(
    integration_client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con el interruptor encendido, hay que verificar el correo para vender y para publicar."""
    # El catálogo se monta con el interruptor apagado (como en el prototipo) y luego se enciende.
    seller_token = await _setup_seller(integration_client, db_session)
    category = await _create_category(integration_client, db_session)
    product_id = await _publish_product(integration_client, seller_token, category["id"])

    monkeypatch.setattr(settings, "REQUIRE_VERIFIED_EMAIL", True)

    # Vender: un usuario sin verificar no puede ni solicitar la tienda...
    await _register(integration_client, "novato@example.com", "Novato")
    novato_token = await _login(integration_client, "novato@example.com")
    blocked_store = await integration_client.post(
        "/api/v1/sellers/me", json={"name": "Tienda nueva"}, headers=_auth(novato_token)
    )
    assert blocked_store.status_code == 403
    assert blocked_store.json()["code"] == "email_not_verified"

    # ...ni gestionar el catálogo de una tienda ya aprobada (cuelga de `get_approved_store`).
    blocked_product = await integration_client.post(
        "/api/v1/catalog/products",
        json={"title": "Otro producto", "category_id": category["id"], "variants": []},
        headers=_auth(seller_token),
    )
    assert blocked_product.status_code == 403
    assert blocked_product.json()["code"] == "email_not_verified"

    # Publicar: ni preguntas ni reseñas.
    await _register(integration_client, "buyer@example.com", "Buyer")
    buyer_token = await _login(integration_client, "buyer@example.com")
    blocked_question = await integration_client.post(
        f"/api/v1/products/{product_id}/questions",
        json={"body": "¿Tiene garantía?"},
        headers=_auth(buyer_token),
    )
    assert blocked_question.status_code == 403
    assert blocked_question.json()["code"] == "email_not_verified"

    blocked_review = await integration_client.post(
        "/api/v1/reviews",
        json={"product_id": product_id, "rating": 5, "body": "Buena"},
        headers=_auth(buyer_token),
    )
    assert blocked_review.status_code == 403
    assert blocked_review.json()["code"] == "email_not_verified"

    # Al verificar el correo, los dos caminos se desbloquean.
    await _verify_in_db(db_session, "novato@example.com")
    allowed_store = await integration_client.post(
        "/api/v1/sellers/me", json={"name": "Tienda nueva"}, headers=_auth(novato_token)
    )
    assert allowed_store.status_code == 201, allowed_store.text

    await _verify_in_db(db_session, "buyer@example.com")
    allowed_question = await integration_client.post(
        f"/api/v1/products/{product_id}/questions",
        json={"body": "¿Tiene garantía?"},
        headers=_auth(buyer_token),
    )
    assert allowed_question.status_code == 201, allowed_question.text
