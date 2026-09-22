"""Proveedores de pago (interfaz + implementación sandbox).

Cambiar de pasarela (Stripe, MercadoPago, Wompi...) consiste en implementar
`PaymentProvider` y registrarla en `PROVIDERS`: el dominio no cambia.
"""

import hashlib
import hmac
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.core.errors import AppError


@dataclass(frozen=True)
class PaymentIntent:
    """Intento de pago creado en el proveedor."""

    provider_reference: str
    checkout_url: str
    status: str
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class WebhookEvent:
    """Evento normalizado recibido del proveedor."""

    event_id: str
    event_type: str
    provider_reference: str
    status: str
    failure_reason: str | None = None


class PaymentProvider(ABC):
    """Interfaz de pasarela de pago."""

    name: str

    @abstractmethod
    def create_intent(
        self, *, order_id: uuid.UUID, amount: Decimal, currency: str, description: str
    ) -> PaymentIntent:
        """Crea el intento de pago y devuelve dónde pagar."""

    @abstractmethod
    def parse_webhook(self, raw_body: bytes, signature: str | None) -> WebhookEvent:
        """Verifica la firma y normaliza el webhook."""


def sign_payload(raw_body: bytes, secret: str | None = None) -> str:
    """Firma HMAC-SHA256 del cuerpo crudo (la usan el proveedor y el simulador)."""
    key = (secret or settings.PAYMENT_WEBHOOK_SECRET).encode()
    return hmac.new(key, raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, signature: str | None) -> None:
    """Comprueba la firma del webhook en tiempo constante."""
    if not signature:
        raise AppError(401, "invalid_signature", "Missing webhook signature.")
    if not hmac.compare_digest(sign_payload(raw_body), signature):
        raise AppError(401, "invalid_signature", "Invalid webhook signature.")


class SandboxPaymentProvider(PaymentProvider):
    """Pasarela simulada para desarrollo (no cobra de verdad)."""

    name = "sandbox"

    def create_intent(
        self, *, order_id: uuid.UUID, amount: Decimal, currency: str, description: str
    ) -> PaymentIntent:
        reference = f"sbx_{uuid.uuid4().hex}"
        return PaymentIntent(
            provider_reference=reference,
            checkout_url=f"{settings.PAYMENT_CHECKOUT_BASE_URL.rstrip('/')}/{reference}",
            status="pending",
            amount=amount,
            currency=currency,
        )

    def parse_webhook(self, raw_body: bytes, signature: str | None) -> WebhookEvent:
        verify_signature(raw_body, signature)
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            raise AppError(400, "invalid_payload", "Invalid webhook payload.") from None

        data = payload.get("data") if isinstance(payload, dict) else None
        event_id = payload.get("id") if isinstance(payload, dict) else None
        event_type = payload.get("type") if isinstance(payload, dict) else None
        reference = data.get("reference") if isinstance(data, dict) else None
        status_value = data.get("status") if isinstance(data, dict) else None

        if not event_id or not event_type or not reference or not status_value:
            raise AppError(400, "invalid_payload", "Invalid webhook payload.")

        reason = data.get("failure_reason") if isinstance(data, dict) else None
        return WebhookEvent(
            event_id=str(event_id),
            event_type=str(event_type),
            provider_reference=str(reference),
            status=str(status_value),
            failure_reason=str(reason) if reason else None,
        )

    @staticmethod
    def build_webhook_payload(reference: str, outcome: str) -> bytes:
        """Webhook de ejemplo que usa el simulador de sandbox."""
        event = {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": f"payment.{outcome}",
            "data": {
                "reference": reference,
                "status": outcome,
                "failure_reason": "Card declined (sandbox)." if outcome == "failed" else None,
            },
        }
        return json.dumps(event).encode()


PROVIDERS: dict[str, PaymentProvider] = {SandboxPaymentProvider.name: SandboxPaymentProvider()}


def get_provider(name: str) -> PaymentProvider:
    """Devuelve el proveedor registrado o falla si no existe."""
    provider = PROVIDERS.get(name)
    if provider is None:
        raise AppError(404, "unknown_payment_provider", f"Unknown payment provider: {name}.")
    return provider
