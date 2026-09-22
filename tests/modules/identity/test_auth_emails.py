"""Pruebas de integración de los correos de identidad (cola de notificaciones + enlace real).

Se usa el remitente `capturing` (guardado en memoria): **ninguna** prueba abre una conexión SMTP.
Lo que se comprueba es la cadena completa: registrar encola el correo, el worker lo envía con el
asunto y el cuerpo renderizados, y el enlace del correo canjea el token contra la API.
"""

import re
from urllib.parse import unquote

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import CapturingEmailSender, SentEmail
from app.modules.identity.models import User, UserRole

TEST_REDIS_URL = "redis://localhost:6379/1"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def captured_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Captura los correos en memoria en vez de dejarlos en el log."""
    monkeypatch.setattr(settings, "EMAIL_SENDER", "capturing")
    CapturingEmailSender.reset()


async def _reset_register_rate_limit() -> None:
    """Limpia el límite de registros (varios usuarios por prueba desde la misma IP)."""
    redis: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        keys = await redis.keys("rate_limit:register:*")
        if keys:
            await redis.delete(*keys)
    finally:
        await redis.aclose()


async def _login(client: AsyncClient, email: str, password: str = "secret123") -> str:
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])


async def _register(
    client: AsyncClient,
    email: str,
    *,
    full_name: str = "Comprador",
    password: str = "secret123",
) -> str:
    """Registra un usuario y devuelve su access token."""
    await _reset_register_rate_limit()
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return await _login(client, email, password)


async def _admin_token(client: AsyncClient, db_session: AsyncSession) -> str:
    """Crea un admin (el que procesa la cola de correos) y devuelve su access token."""
    await _register(client, "admin@example.com", full_name="Admin")
    result = await db_session.execute(select(User).where(User.email == "admin@example.com"))
    result.scalar_one().role = UserRole.ADMIN
    await db_session.commit()
    return await _login(client, "admin@example.com")


async def _process_queue(client: AsyncClient, admin_token: str) -> dict[str, int]:
    response = await client.post("/api/v1/admin/notifications/process", headers=_auth(admin_token))
    assert response.status_code == 200, response.text
    return dict(response.json())


def _link_token(email: SentEmail, *, path: str) -> str:
    """Saca el token del enlace del correo (`{FRONTEND_URL}/{idioma}/{path}?token=...`)."""
    match = re.search(
        rf"{re.escape(settings.FRONTEND_URL)}/[a-z]{{2}}/{re.escape(path)}\?token=(\S+)", email.body
    )
    assert match is not None, email.body
    return unquote(match.group(1))


async def test_register_queues_the_verification_email_and_the_link_works(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session)
    buyer = await _register(integration_client, "buyer@example.com", full_name="Juan Pérez")
    CapturingEmailSender.reset()

    # El correo queda en cola: el registro no espera al servidor de correo.
    emails = (
        await integration_client.get(
            "/api/v1/admin/notifications/emails", headers=_auth(admin), params={"limit": 5}
        )
    ).json()
    assert emails[0]["email_to"] == "buyer@example.com"
    assert emails[0]["email_status"] == "queued"
    assert emails[0]["type"] == "email_verification"

    # Y no es un aviso in-app: la campana del comprador sigue vacía.
    bell = (await integration_client.get("/api/v1/notifications", headers=_auth(buyer))).json()
    assert bell["items"] == []
    assert bell["unread_count"] == 0

    result = await _process_queue(integration_client, admin)
    assert result["sent"] >= 1
    assert result["pending"] == 0

    # El correo sale en español, con el nombre del usuario y el enlace al frontend.
    sent = [email for email in CapturingEmailSender.sent if email.to == "buyer@example.com"]
    assert len(sent) == 1
    assert "Confirma tu correo" in sent[0].subject
    assert "Juan Pérez" in sent[0].body
    assert f"{settings.FRONTEND_URL}/es/verify-email?token=" in sent[0].body

    # El enlace del correo funciona de verdad: canjea el token y el correo queda verificado.
    verified = await integration_client.post(
        "/api/v1/auth/verify-email", json={"token": _link_token(sent[0], path="verify-email")}
    )
    assert verified.status_code == 204, verified.text

    me = (await integration_client.get("/api/v1/users/me", headers=_auth(buyer))).json()
    assert me["email_verified"] is True

    after = (
        await integration_client.get(
            "/api/v1/admin/notifications/emails", headers=_auth(admin), params={"limit": 5}
        )
    ).json()
    assert after[0]["email_status"] == "sent"
    assert after[0]["sent_at"] is not None


async def test_password_reset_email_uses_the_profile_language(
    integration_client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _admin_token(integration_client, db_session)
    buyer = await _register(integration_client, "buyer@example.com", full_name="John Smith")

    # El idioma del perfil manda en la plantilla y en el idioma del enlace.
    updated = await integration_client.patch(
        "/api/v1/users/me", json={"preferred_language": "en"}, headers=_auth(buyer)
    )
    assert updated.status_code == 200, updated.text

    # Se vacía la cola antes de medir: los correos del alta (verificación) ya estaban esperando.
    await _process_queue(integration_client, admin)
    CapturingEmailSender.reset()

    forgot = await integration_client.post(
        "/api/v1/auth/forgot-password", json={"email": "buyer@example.com"}
    )
    assert forgot.status_code == 202, forgot.text

    await _process_queue(integration_client, admin)

    sent = [email for email in CapturingEmailSender.sent if email.to == "buyer@example.com"]
    assert len(sent) == 1
    assert sent[0].subject == f"Reset your password at {settings.PROJECT_NAME}"
    assert f"{settings.FRONTEND_URL}/en/reset-password?token=" in sent[0].body

    # El enlace del correo cambia la contraseña de verdad.
    reset = await integration_client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": _link_token(sent[0], path="reset-password"),
            "new_password": "nueva-clave-123",
        },
    )
    assert reset.status_code == 204, reset.text

    login = await integration_client.post(
        "/api/v1/auth/login", json={"email": "buyer@example.com", "password": "nueva-clave-123"}
    )
    assert login.status_code == 200, login.text
