"""Pruebas unitarias del envío de emails.

Ninguna prueba abre una conexión real: el envío SMTP se prueba sustituyendo `aiosmtplib.send`, y
el resto de remitentes (log, captura, fallo) no tocan la red por diseño.
"""

from typing import Any

import aiosmtplib
import pytest

from app.core.config import settings
from app.core.email import (
    CapturingEmailSender,
    EmailSender,
    LoggingEmailSender,
    SentEmail,
    SmtpEmailSender,
    build_message,
    get_email_sender,
)


def test_default_sender_is_logging() -> None:
    """Sin configurar nada (y en las pruebas, por el `conftest`) no se envía a la red."""
    assert settings.EMAIL_SENDER == "logging"
    assert isinstance(get_email_sender(), LoggingEmailSender)


def test_unknown_sender_falls_back_to_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un valor mal escrito en el .env no puede dejar los correos sin enviar en silencio."""
    monkeypatch.setattr(settings, "EMAIL_SENDER", "un-sender-que-no-existe")
    assert isinstance(get_email_sender(), LoggingEmailSender)


def test_build_message_sets_headers_and_body() -> None:
    """El mensaje lleva remitente, destinatario, asunto y cuerpo con acentos."""
    message = build_message(
        to="buyer@example.com", subject="Confirma tu correo", body="Cuerpo con ñ y á"
    )
    assert message["From"] == settings.EMAIL_FROM
    assert message["To"] == "buyer@example.com"
    assert str(message["Subject"]) == "Confirma tu correo"
    assert "ñ y á" in message.get_content()


def test_build_message_prefers_smtp_from_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SMTP_FROM", "contacto@marketplace.local")
    message = build_message(to="buyer@example.com", subject="Asunto", body="Cuerpo")
    assert message["From"] == "contacto@marketplace.local"


async def test_smtp_sender_uses_the_configured_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """El envío SMTP respeta host, puerto y modo TLS del `.env` (Mailpit en desarrollo)."""
    calls: list[dict[str, Any]] = []

    async def fake_send(message: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        calls.append({"message": message, **kwargs})
        return {}, ""

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    await SmtpEmailSender().send(to="buyer@example.com", subject="Asunto", body="Cuerpo")

    assert len(calls) == 1
    assert calls[0]["hostname"] == settings.SMTP_HOST
    assert calls[0]["port"] == settings.SMTP_PORT
    assert calls[0]["username"] is None  # Mailpit no pide autenticación
    assert calls[0]["use_tls"] is False
    assert calls[0]["start_tls"] is None  # STARTTLS automático si el servidor lo ofrece
    assert calls[0]["message"]["To"] == "buyer@example.com"


async def test_smtp_sender_with_direct_tls_disables_start_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con TLS directo (puerto 465) no se intenta además STARTTLS, y se autentica si hay usuario."""
    calls: list[dict[str, Any]] = []

    async def fake_send(message: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        calls.append({"message": message, **kwargs})
        return {}, ""

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USER", "smtp-user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "smtp-password")

    await SmtpEmailSender().send(to="buyer@example.com", subject="Asunto", body="Cuerpo")

    assert calls[0]["use_tls"] is True
    assert calls[0]["start_tls"] is False
    assert calls[0]["username"] == "smtp-user"
    assert calls[0]["password"] == "smtp-password"


async def test_capturing_sender_stores_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """El remitente de pruebas guarda lo enviado en memoria (lo usan las pruebas de integración)."""
    monkeypatch.setattr(settings, "EMAIL_SENDER", "capturing")
    CapturingEmailSender.reset()

    sender: EmailSender = get_email_sender()
    await sender.send(to="buyer@example.com", subject="Asunto", body="Cuerpo")

    assert CapturingEmailSender.sent == [
        SentEmail(to="buyer@example.com", subject="Asunto", body="Cuerpo")
    ]

    CapturingEmailSender.reset()
    assert CapturingEmailSender.sent == []
