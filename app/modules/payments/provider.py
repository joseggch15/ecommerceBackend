"""Proveedores de pago (interfaz + implementación sandbox).

Cambiar de pasarela (Mercado Pago, Stripe, Wompi...) consiste en implementar `PaymentProvider`
y registrarla en `PROVIDERS`: el dominio no cambia.

La interfaz es **asíncrona** porque una pasarela real hace llamadas HTTP y, además, el webhook
hay que **confirmarlo contra la API del proveedor** (estado y monto) antes de dar una orden por
pagada: nunca se confía en lo que llega en el aviso.
"""

import hashlib
import hmac
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
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
    """Evento normalizado recibido del proveedor.

    `amount`, `currency` y `order_id` los rellena el proveedor **después de consultar el pago**
    en su API (no vienen del aviso): son los que permiten confirmar que lo cobrado es lo que
    había que cobrar.
    """

    event_id: str
    event_type: str
    provider_reference: str
    status: str
    failure_reason: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    order_id: uuid.UUID | None = None


class PaymentProvider(ABC):
    """Interfaz de pasarela de pago."""

    name: str

    @abstractmethod
    async def create_intent(
        self,
        *,
        order_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        description: str,
        idempotency_key: str | None = None,
        notification_url: str | None = None,
    ) -> PaymentIntent:
        """Crea el intento de pago y devuelve dónde pagar.

        `idempotency_key` permite reintentar sin crear dos cobros; `notification_url` es la URL a la
        que el proveedor avisará del resultado (webhook).
        """

    @abstractmethod
    async def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Verifica la firma, confirma el pago contra la API del proveedor y normaliza el evento."""


def sign_payload(raw_body: bytes, secret: str | None = None) -> str:
    """Firma HMAC-SHA256 del cuerpo crudo (la usan el proveedor sandbox y el simulador)."""
    key = (secret or settings.PAYMENT_WEBHOOK_SECRET).encode()
    return hmac.new(key, raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, signature: str | None) -> None:
    """Comprueba la firma del webhook en tiempo constante."""
    if not signature:
        raise AppError(401, "invalid_signature", "Missing webhook signature.")
    if not hmac.compare_digest(sign_payload(raw_body), signature):
        raise AppError(401, "invalid_signature", "Invalid webhook signature.")


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """Busca un encabezado sin depender de mayúsculas y minúsculas (un dict de pruebas no lo es)."""
    wanted = name.lower()

    for key, value in headers.items():
        if key.lower() == wanted:
            return value

    return None


class SandboxPaymentProvider(PaymentProvider):
    """Pasarela simulada para desarrollo (no cobra de verdad)."""

    name = "sandbox"

    async def create_intent(
        self,
        *,
        order_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        description: str,
        idempotency_key: str | None = None,
        notification_url: str | None = None,
    ) -> PaymentIntent:
        reference = f"sbx_{uuid.uuid4().hex}"
        return PaymentIntent(
            provider_reference=reference,
            checkout_url=f"{settings.PAYMENT_CHECKOUT_BASE_URL.rstrip('/')}/{reference}",
            status="pending",
            amount=amount,
            currency=currency,
        )

    async def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        verify_signature(raw_body, header_value(headers, "x-signature"))
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


def register_provider(provider: PaymentProvider) -> None:
    """Registra una pasarela (lo usa el adaptador de Mercado Pago al importarse)."""
    PROVIDERS[provider.name] = provider


def get_provider(name: str) -> PaymentProvider:
    """Devuelve el proveedor registrado o falla si no existe."""
    provider = PROVIDERS.get(name)
    if provider is None:
        raise AppError(404, "unknown_payment_provider", f"Unknown payment provider: {name}.")
    return provider
