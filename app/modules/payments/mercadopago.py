"""Adaptador de Mercado Pago (pasarela principal del proyecto).

**Qué hace, en corto:**

1. Al crear el pago de una orden crea una **preferencia** en Mercado Pago (Checkout Bricks /
   Checkout Pro) con el monto que calcula el backend, la moneda de la orden y
   `external_reference` = id de la orden. La petición lleva una clave de idempotencia derivada
   de la orden y del intento, así que reintentar no crea dos cobros.
2. Al recibir un webhook **verifica la firma** y después **consulta el pago en la API del
   proveedor**: el aviso no se cree, solo se usa como disparador. El estado y el monto que se
   aplican son los que responde la API, y el servicio compara el monto con el de la orden antes
   de darla por pagada.

**Sobre los detalles del protocolo** (encabezados y plantilla de firma): viven en configuración
(`MERCADOPAGO_SIGNATURE_HEADER`, `MERCADOPAGO_REQUEST_ID_HEADER`,
`MERCADOPAGO_IDEMPOTENCY_HEADER`, `MERCADOPAGO_SIGNATURE_TEMPLATE`). Los valores por defecto son
los que documenta Mercado Pago para las notificaciones webhook v2 (`x-signature` con
`ts=...,v1=...`, `x-request-id`, plantilla `id:{data_id};request-id:{request_id};ts:{ts};`) y
para idempotencia (`X-Idempotency-Key`).

⚠️ **No se pudo verificar la documentación oficial desde el entorno de desarrollo** (las páginas
devuelven 404 o exigen JavaScript) y el peso colombiano (COP) no usa centavos en la práctica, así
que el monto se envía **entero** por defecto (`MERCADOPAGO_AMOUNT_MODE=integer`). Antes de cobrar
de verdad hay que confirmar esos tres puntos con la documentación del proveedor (decisión 0019).
Si cambian, se corrigen **en configuración**, sin tocar el código.
"""

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import AppError
from app.modules.payments.provider import (
    PaymentIntent,
    PaymentProvider,
    WebhookEvent,
    header_value,
    register_provider,
)

# Estados de Mercado Pago -> estados normalizados del módulo de pagos.
STATUS_MAP: dict[str, str] = {
    "approved": "succeeded",
    "authorized": "processing",
    "in_process": "processing",
    "pending": "pending",
    "rejected": "failed",
    "cancelled": "cancelled",
    "refunded": "refunded",
    "charged_back": "refunded",
}


def parse_signature_header(value: str) -> dict[str, str]:
    """Parte el encabezado de firma (`ts=1712345678,v1=abcdef`) en sus campos."""
    fields: dict[str, str] = {}

    for chunk in value.split(","):
        key, _, raw = chunk.partition("=")
        if key and raw:
            fields[key.strip()] = raw.strip()

    return fields


def build_manifest(*, data_id: str, request_id: str, ts: str, template: str | None = None) -> str:
    """Construye la cadena que se firma, con la plantilla configurada."""
    return (template or settings.MERCADOPAGO_SIGNATURE_TEMPLATE).format(
        data_id=data_id, request_id=request_id, ts=ts
    )


def compute_signature(*, manifest: str, secret: str) -> str:
    """HMAC-SHA256 en hexadecimal de la cadena firmada."""
    return hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()


def verify_webhook_signature(*, headers: Mapping[str, str], data_id: str, secret: str) -> None:
    """Verifica la firma del webhook en tiempo constante (nunca se compara con `==`)."""
    raw_signature = header_value(headers, settings.MERCADOPAGO_SIGNATURE_HEADER)
    if not raw_signature:
        raise AppError(401, "invalid_signature", "Missing webhook signature.")
    if not secret:
        raise AppError(
            503, "payment_provider_not_configured", "Mercado Pago webhook secret is not configured."
        )

    fields = parse_signature_header(raw_signature)
    ts = fields.get("ts")
    provided = fields.get("v1")
    if not ts or not provided:
        raise AppError(401, "invalid_signature", "Invalid webhook signature header.")

    request_id = header_value(headers, settings.MERCADOPAGO_REQUEST_ID_HEADER) or ""
    manifest = build_manifest(data_id=data_id, request_id=request_id, ts=ts)

    if not hmac.compare_digest(compute_signature(manifest=manifest, secret=secret), provided):
        raise AppError(401, "invalid_signature", "Invalid webhook signature.")


def amount_for_provider(amount: Decimal, mode: str | None = None) -> int | float:
    """Convierte el monto al formato que espera la API del proveedor.

    - `integer` (por defecto): entero, sin decimales (como se usa el peso colombiano).
    - `decimal`: con dos decimales. Aquí sí hay un `float`, pero solo en el **transporte** (el JSON
      que se envía); el monto de la orden se sigue calculando con `Decimal`.
    """
    value = Decimal(str(amount))

    if (mode or settings.MERCADOPAGO_AMOUNT_MODE).lower() == "decimal":
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def order_id_from_reference(reference: Any) -> uuid.UUID | None:
    """Convierte el `external_reference` del proveedor en el id de la orden.

    Devuelve `None` si el proveedor no manda un UUID.
    """

    if not isinstance(reference, str):
        return None

    try:
        return uuid.UUID(reference)
    except ValueError:
        return None


class MercadoPagoProvider(PaymentProvider):
    """Pasarela Mercado Pago por su API REST (Checkout Bricks / Checkout Pro)."""

    name = "mercadopago"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        webhook_secret: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._access_token = (
            access_token if access_token is not None else settings.MERCADOPAGO_ACCESS_TOKEN
        )
        self._webhook_secret = (
            webhook_secret if webhook_secret is not None else settings.MERCADOPAGO_WEBHOOK_SECRET
        )
        self._base_url = (base_url or settings.MERCADOPAGO_API_BASE_URL).rstrip("/")
        # Transporte inyectable: las pruebas usan `httpx.MockTransport`, nunca la API real.
        self._transport = transport

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
        """Crea la preferencia de pago y devuelve la URL de checkout del proveedor."""
        self._ensure_configured()

        payload: dict[str, Any] = {
            "items": [
                {
                    "title": description,
                    "quantity": 1,
                    "currency_id": currency,
                    "unit_price": amount_for_provider(amount),
                }
            ],
            "external_reference": str(order_id),
            "statement_descriptor": settings.PROJECT_NAME,
        }
        if notification_url:
            payload["notification_url"] = notification_url

        data = await self._request(
            "POST", "/checkout/preferences", payload=payload, idempotency_key=idempotency_key
        )

        preference_id = data.get("id")
        checkout_url = data.get("init_point") or data.get("sandbox_init_point")
        if not preference_id or not checkout_url:
            raise AppError(
                502,
                "payment_provider_error",
                "Mercado Pago did not return a preference to pay with.",
            )

        return PaymentIntent(
            provider_reference=str(preference_id),
            checkout_url=str(checkout_url),
            status="pending",
            amount=amount,
            currency=currency,
        )

    async def parse_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        """Verifica la firma y confirma el pago consultándolo en la API del proveedor."""
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            raise AppError(400, "invalid_payload", "Invalid webhook payload.") from None

        data = payload.get("data") if isinstance(payload, dict) else None
        data_id = data.get("id") if isinstance(data, dict) else None
        if data_id is None:
            raise AppError(400, "invalid_payload", "Invalid webhook payload: missing payment id.")

        verify_webhook_signature(headers=headers, data_id=str(data_id), secret=self._webhook_secret)

        payment = await self._request("GET", f"/v1/payments/{data_id}")
        provider_status = str(payment.get("status") or "")
        transaction_amount = payment.get("transaction_amount")

        return WebhookEvent(
            event_id=str(payload.get("id") or f"mp_{data_id}"),
            event_type=f"payment.{provider_status or 'unknown'}",
            # El id del pago (no el de la preferencia): es lo que el proveedor conoce de este cobro.
            provider_reference=str(payment.get("id") or data_id),
            status=STATUS_MAP.get(provider_status, "pending"),
            failure_reason=str(payment.get("status_detail"))
            if provider_status in {"rejected", "cancelled", "refunded"}
            else None,
            amount=Decimal(str(transaction_amount)) if transaction_amount is not None else None,
            currency=str(payment.get("currency_id")) if payment.get("currency_id") else None,
            order_id=order_id_from_reference(payment.get("external_reference")),
        )

    # ---------- Internos ----------

    def _ensure_configured(self) -> None:
        if not self._access_token:
            raise AppError(
                503,
                "payment_provider_not_configured",
                "Mercado Pago is not configured (missing access token).",
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Llamada a la API del proveedor (las pruebas usan un transporte falso, no la API real)."""
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers[settings.MERCADOPAGO_IDEMPOTENCY_HEADER] = idempotency_key

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, transport=self._transport, timeout=20.0
            ) as client:
                response = await client.request(method, path, json=payload, headers=headers)
        except httpx.HTTPError as error:  # red caída, timeout, DNS...
            raise AppError(
                502, "payment_provider_unavailable", "Mercado Pago is not reachable."
            ) from error

        if response.status_code >= 400:
            raise AppError(
                502,
                "payment_provider_error",
                f"Mercado Pago responded {response.status_code}.",
            )

        data = response.json()
        if not isinstance(data, dict):
            raise AppError(502, "payment_provider_error", "Unexpected response from Mercado Pago.")

        return data


mercadopago_provider = MercadoPagoProvider()
register_provider(mercadopago_provider)
