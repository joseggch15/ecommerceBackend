"""Pruebas de integración del módulo de identidad (autenticación)."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_opaque_token, hash_token
from app.modules.identity.models import TokenType, UserToken


async def _register(
    client: AsyncClient,
    email: str = "buyer@example.com",
    password: str = "secret123",
    full_name: str = "Comprador",
) -> Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


async def _login(
    client: AsyncClient,
    email: str = "buyer@example.com",
    password: str = "secret123",
) -> Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_register_returns_user_and_tokens(integration_client: AsyncClient) -> None:
    """El registro crea la cuenta **y deja la sesión iniciada** (apartado 15, decisión 0023)."""
    resp = await _register(integration_client)
    assert resp.status_code == 201
    body = resp.json()

    user = body["user"]
    assert user["email"] == "buyer@example.com"
    assert user["role"] == "customer"
    assert user["email_verified"] is False
    assert user["profile"]["full_name"] == "Comprador"
    assert user["profile"]["preferred_currency"] == "COP"

    # Los tokens del registro valen tal cual: no hace falta volver a iniciar sesión.
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]

    me = await integration_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == user["id"]

    # Y el refresh token también es real (rota el par).
    refreshed = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


async def test_register_duplicate_email_conflict(integration_client: AsyncClient) -> None:
    await _register(integration_client)
    resp = await _register(integration_client)
    assert resp.status_code == 409
    assert resp.json()["code"] == "email_already_registered"


async def test_login_wrong_password_unauthorized(integration_client: AsyncClient) -> None:
    await _register(integration_client)
    resp = await _login(integration_client, password="wrong-password")
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_credentials"


async def test_refresh_rotates_token(integration_client: AsyncClient) -> None:
    await _register(integration_client)
    tokens = (await _login(integration_client)).json()

    refreshed = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # El refresh anterior quedó revocado: reutilizarlo debe fallar.
    reused = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reused.status_code == 401


async def test_logout_revokes_refresh_token(integration_client: AsyncClient) -> None:
    await _register(integration_client)
    tokens = (await _login(integration_client)).json()

    logout = await integration_client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert logout.status_code == 204

    refreshed = await integration_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 401


async def test_verify_email(integration_client: AsyncClient, db_session: AsyncSession) -> None:
    register_resp = await _register(integration_client)
    user_id = uuid.UUID(register_resp.json()["user"]["id"])

    raw = generate_opaque_token()
    db_session.add(
        UserToken(
            user_id=user_id,
            type=TokenType.EMAIL_VERIFICATION,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    resp = await integration_client.post("/api/v1/auth/verify-email", json={"token": raw})
    assert resp.status_code == 204

    tokens = (await _login(integration_client)).json()
    me = await integration_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["email_verified"] is True


async def test_reset_password_flow(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    register_resp = await _register(integration_client)
    user_id = uuid.UUID(register_resp.json()["user"]["id"])

    raw = generate_opaque_token()
    db_session.add(
        UserToken(
            user_id=user_id,
            type=TokenType.PASSWORD_RESET,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db_session.commit()

    resp = await integration_client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "new_password": "new-secret-123"}
    )
    assert resp.status_code == 204

    # La contraseña anterior ya no funciona; la nueva sí.
    assert (await _login(integration_client, password="secret123")).status_code == 401
    assert (await _login(integration_client, password="new-secret-123")).status_code == 200
