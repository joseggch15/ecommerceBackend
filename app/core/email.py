"""Envío de emails detrás de una interfaz (en desarrollo se escribe en el log)."""

import logging
from abc import ABC, abstractmethod

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


class FailingEmailSender(EmailSender):
    """Implementación de pruebas: siempre falla (para probar reintentos)."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        raise RuntimeError(f"SMTP unavailable (test) for {to}")


# Registro de remitentes: cambiar el envío es añadir una entrada y ajustar el .env.
SENDERS: dict[str, type[EmailSender]] = {
    "logging": LoggingEmailSender,
    "failing": FailingEmailSender,
}


def get_email_sender() -> EmailSender:
    """Devuelve el remitente configurado en `EMAIL_SENDER`."""
    sender_class = SENDERS.get(settings.EMAIL_SENDER, LoggingEmailSender)
    return sender_class()
