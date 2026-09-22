"""Envío de emails detrás de una interfaz.

El remitente se elige con `EMAIL_SENDER`:

- `logging` (por defecto): no sale nada a la red, el correo queda en el log.
- `smtp`: envío real por SMTP. En desarrollo apunta a **Mailpit** (`SMTP_HOST=localhost`,
  `SMTP_PORT=1025`), que guarda los correos para verlos en su interfaz web (8025) en lugar de
  mandarlos a un buzón de verdad.
- `capturing` (pruebas) y `failing` (pruebas de reintento): dobles de prueba, nunca tocan la red.

Cambiar de proveedor (SES, SendGrid...) es añadir una clase al registro `SENDERS`: el dominio no
se entera.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from typing import ClassVar

import aiosmtplib

from app.core.config import settings


class EmailSender(ABC):
    """Interfaz de envío de emails (permite cambiar a SES, SendGrid, SMTP...)."""

    @abstractmethod
    async def send(self, *, to: str, subject: str, body: str) -> None:
        """Envía un email; lanza excepción si falla."""


class LoggingEmailSender(EmailSender):
    """Implementación de desarrollo: no envía nada, deja el email en el log."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logging.getLogger("app.email").info(
            "email_sent", extra={"to": to, "subject": subject, "body": body}
        )


@dataclass(frozen=True)
class SentEmail:
    """Correo que un remitente de prueba guardó en memoria."""

    to: str
    subject: str
    body: str


class CapturingEmailSender(EmailSender):
    """Implementación de pruebas: guarda lo enviado en memoria para poder afirmarlo."""

    sent: ClassVar[list[SentEmail]] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        CapturingEmailSender.sent.append(SentEmail(to=to, subject=subject, body=body))

    @classmethod
    def reset(cls) -> None:
        """Vacía lo capturado (lo llaman las pruebas entre casos)."""
        cls.sent.clear()


class FailingEmailSender(EmailSender):
    """Implementación de pruebas: siempre falla (para probar reintentos)."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        raise RuntimeError(f"SMTP unavailable (test) for {to}")


def build_message(*, to: str, subject: str, body: str) -> EmailMessage:
    """Construye el mensaje (texto plano UTF-8) con remitente y destinatario.

    Se usa `EmailMessage.set_content` para que el cuerpo se codifique según el estándar: acentos,
    `ñ` y los enlaces largos viajan sin romperse.
    """
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM or settings.EMAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


class SmtpEmailSender(EmailSender):
    """Envío real por SMTP con `aiosmtplib` (asíncrono: no bloquea el event loop)."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = build_message(to=to, subject=subject, body=body)
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            # Sin usuario configurado (Mailpit) no se intenta autenticar.
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=settings.SMTP_USE_TLS,
            # `None` = STARTTLS automático si el servidor lo ofrece; con TLS directo, no.
            start_tls=False if settings.SMTP_USE_TLS else None,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
        )


# Registro de remitentes: cambiar el envío es añadir una entrada y ajustar el .env.
SENDERS: dict[str, type[EmailSender]] = {
    "logging": LoggingEmailSender,
    "smtp": SmtpEmailSender,
    "capturing": CapturingEmailSender,
    "failing": FailingEmailSender,
}


def get_email_sender() -> EmailSender:
    """Devuelve el remitente configurado en `EMAIL_SENDER` (si el valor no existe, `logging`)."""
    sender_class = SENDERS.get(settings.EMAIL_SENDER, LoggingEmailSender)
    return sender_class()
