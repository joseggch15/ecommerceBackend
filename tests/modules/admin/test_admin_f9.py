"""Pruebas de integración de las dos lagunas de administración (F9).

1. **Directorio de usuarios**: `GET /admin/users` (búsqueda por correo, filtro por rol, cursor).
   Solo para administradores y **sin** hashes de contraseña ni tokens en la respuesta.
2. **Moderación de preguntas**: listar, ocultar y republicar, igual que la moderación de reseñas.

Como en todo el proyecto, el catálogo de partida se monta con la API real (registro, tienda,
aprobación y publicación) y la pregunta la escribe un comprador de verdad.
"""

from typing import Any

from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.modules.catalog.test_products import _auth, _create_category, _login, _setup_seller

TEST_REDIS_URL = "redis://localhost:6379/1"
USERS_URL = "/api/v1/admin/users"
QUESTIONS_URL = "/api/v1/admin/questions"


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


async def _register(client: AsyncClient, email: str, full_name: str) -> str:
    """Registra e inicia sesión; devuelve el access token."""
    await _reset_auth_rate_limits()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret123", "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return await _login(client, email)


async def _setup(client: AsyncClient, db_session: AsyncSession) -> dict[str, Any]:
    """Admin, vendedor con tienda aprobada, producto publicado y comprador que pregunta."""
    seller_token = await _setup_seller(client, db_session)
    category = await _create_category(client, db_session)
    admin_token = await _login(client, "admin@example.com")

    product = (
        await client.post(
            "/api/v1/catalog/products",
            json={
                "title": "Producto F9",
                "category_id": category["id"],
                "variants": [{"sku": "SKU-F9", "price": "25000", "stock": 10}],
            },
            headers=_auth(seller_token),
        )
    ).json()
    await client.post(
        f"/api/v1/catalog/products/{product['id']}/publish", headers=_auth(seller_token)
    )

    buyer_token = await _register(client, "buyer@example.com", "Comprador")
    question = (
        await client.post(
            f"/api/v1/products/{product['id']}/questions",
            json={"body": "¿Tiene garantía de un año?"},
            headers=_auth(buyer_token),
        )
    ).json()

    return {
        "admin": admin_token,
        "seller": seller_token,
        "buyer": buyer_token,
        "product_id": product["id"],
        "question_id": question["id"],
    }


async def _users(client: AsyncClient, token: str, **params: Any) -> dict[str, Any]:
    response = await client.get(USERS_URL, params=params, headers=_auth(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_list_users_with_search_and_role_filter(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup(integration_client, db_session)

    page = await _users(integration_client, ctx["admin"])
    assert {item["email"] for item in page["items"]} == {
        "admin@example.com",
        "seller@example.com",
        "buyer@example.com",
    }
    assert page["next_cursor"] is None

    seller = next(i for i in page["items"] if i["email"] == "seller@example.com")
    assert seller["role"] == "customer"  # no hay rol «seller»: vende porque tiene tienda
    assert seller["full_name"] == "Seller"
    assert seller["store_name"] == "Tienda"
    assert seller["store_status"] == "approved"
    assert seller["email_verified"] is False

    admin = next(i for i in page["items"] if i["email"] == "admin@example.com")
    assert admin["role"] == "admin"
    assert admin["store_id"] is None

    searched = await _users(integration_client, ctx["admin"], q="seller")
    assert [i["email"] for i in searched["items"]] == ["seller@example.com"]

    admins = await _users(integration_client, ctx["admin"], role="admin")
    assert [i["email"] for i in admins["items"]] == ["admin@example.com"]

    customers = await _users(integration_client, ctx["admin"], role="customer")
    assert {i["email"] for i in customers["items"]} == {
        "seller@example.com",
        "buyer@example.com",
    }

    # Búsqueda por correo parcial y caso sin resultados.
    assert len((await _users(integration_client, ctx["admin"], q="example.com"))["items"]) == 3
    assert (await _users(integration_client, ctx["admin"], q="nadie@example.com"))["items"] == []

    # Rol inexistente y límite fuera de rango: los valida Pydantic.
    assert (
        await integration_client.get(
            USERS_URL, params={"role": "vendedor"}, headers=_auth(ctx["admin"])
        )
    ).status_code == 422
    assert (
        await integration_client.get(USERS_URL, params={"limit": 0}, headers=_auth(ctx["admin"]))
    ).status_code == 422


async def test_users_list_never_exposes_credentials(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Ni hashes de contraseña ni tokens: los campos no se consultan siquiera."""
    ctx = await _setup(integration_client, db_session)

    response = await integration_client.get(USERS_URL, headers=_auth(ctx["admin"]))
    assert response.status_code == 200, response.text
    for item in response.json()["items"]:
        assert set(item) == {
            "id",
            "email",
            "role",
            "email_verified",
            "full_name",
            "store_id",
            "store_name",
            "store_status",
            "created_at",
        }

    body = response.text.lower()
    for secret in ("password", "token", "argon2", "hash"):
        assert secret not in body


async def test_users_list_paginates_by_cursor(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup(integration_client, db_session)

    first = await _users(integration_client, ctx["admin"], limit=2)
    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = await _users(integration_client, ctx["admin"], limit=2, cursor=first["next_cursor"])
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None

    # Sin repeticiones ni huecos entre páginas.
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 3

    broken = await integration_client.get(
        USERS_URL, params={"cursor": "no-es-un-cursor"}, headers=_auth(ctx["admin"])
    )
    assert broken.status_code == 400
    assert broken.json()["code"] == "invalid_cursor"


async def test_user_directory_is_admin_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup(integration_client, db_session)

    for token in (ctx["buyer"], ctx["seller"]):
        response = await integration_client.get(USERS_URL, headers=_auth(token))
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"

    assert (await integration_client.get(USERS_URL)).status_code == 401


async def _questions(client: AsyncClient, token: str, **params: Any) -> dict[str, Any]:
    response = await client.get(QUESTIONS_URL, params=params, headers=_auth(token))
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_question_moderation_hides_and_restores(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup(integration_client, db_session)
    public_url = f"/api/v1/products/{ctx['product_id']}/questions"

    listing = await _questions(integration_client, ctx["admin"])
    assert len(listing["items"]) == 1
    row = listing["items"][0]
    assert row["id"] == ctx["question_id"]
    assert row["product_title"] == "Producto F9"
    assert row["body"] == "¿Tiene garantía de un año?"
    assert row["is_published"] is True
    assert row["answer_count"] == 0

    # El vendedor responde y el contador de la moderación lo refleja.
    answered = await integration_client.post(
        f"/api/v1/questions/{ctx['question_id']}/answers",
        json={"body": "Sí, un año."},
        headers=_auth(ctx["seller"]),
    )
    assert answered.status_code == 201, answered.text
    assert (await _questions(integration_client, ctx["admin"]))["items"][0]["answer_count"] == 1

    hidden = await integration_client.post(
        f"{QUESTIONS_URL}/{ctx['question_id']}/hide",
        json={"reason": "Contenido inapropiado"},
        headers=_auth(ctx["admin"]),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["action"] == "question.hide"
    assert hidden.json()["reason"] == "Contenido inapropiado"
    assert hidden.json()["target_type"] == "question"

    # Fuera del listado público del producto (con sus respuestas dentro) y sin poder responderla.
    assert (await integration_client.get(public_url)).json()["items"] == []
    blocked = await integration_client.post(
        f"/api/v1/questions/{ctx['question_id']}/answers",
        json={"body": "Otra respuesta"},
        headers=_auth(ctx["seller"]),
    )
    assert blocked.status_code == 404
    assert blocked.json()["code"] == "question_not_found"

    # El administrador sí la ve, filtrando por visibilidad.
    only_hidden = await _questions(integration_client, ctx["admin"], published="false")
    assert [item["id"] for item in only_hidden["items"]] == [ctx["question_id"]]
    assert only_hidden["items"][0]["is_published"] is False
    assert (await _questions(integration_client, ctx["admin"], published="true"))["items"] == []

    restored = await integration_client.post(
        f"{QUESTIONS_URL}/{ctx['question_id']}/publish", headers=_auth(ctx["admin"])
    )
    assert restored.status_code == 200
    assert restored.json()["action"] == "question.publish"
    public = (await integration_client.get(public_url)).json()
    assert len(public["items"]) == 1
    assert len(public["items"][0]["answers"]) == 1

    # Todo queda auditado, lo más reciente primero.
    actions = (
        await integration_client.get("/api/v1/admin/actions", headers=_auth(ctx["admin"]))
    ).json()
    assert [action["action"] for action in actions] == ["question.publish", "question.hide"]


async def test_question_moderation_is_admin_only(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _setup(integration_client, db_session)
    hide_url = f"{QUESTIONS_URL}/{ctx['question_id']}/hide"

    for token in (ctx["buyer"], ctx["seller"]):
        assert (
            await integration_client.get(QUESTIONS_URL, headers=_auth(token))
        ).status_code == 403
        denied = await integration_client.post(
            hide_url, json={"reason": "Yo no soy admin"}, headers=_auth(token)
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "forbidden"

    assert (await integration_client.get(QUESTIONS_URL)).status_code == 401
    assert (await integration_client.post(hide_url)).status_code == 401

    # La pregunta sigue publicada y una pregunta inexistente responde 404.
    assert (
        len(
            (
                await integration_client.get(f"/api/v1/products/{ctx['product_id']}/questions")
            ).json()["items"]
        )
        == 1
    )
    missing = await integration_client.post(
        f"{QUESTIONS_URL}/00000000-0000-0000-0000-000000000000/hide", headers=_auth(ctx["admin"])
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "question_not_found"
