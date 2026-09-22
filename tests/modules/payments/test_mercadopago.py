"""Pruebas del adaptador de Mercado Pago.

**Ninguna prueba llama a la API real del proveedor**: el adaptador acepta un `transport` de httpx y
aquí se le pasa `httpx.MockTransport` con respuestas simuladas. Lo que se protege:

- La petición de la preferencia lleva la clave de idempotencia derivada de la orden y el monto en la
  moneda de la orden (entero para COP, sin centavos).
- Un webhook con firma inválida se rechaza **sin** llegar a consultar el pago en el proveedor.
- El webhook confirmado trae estado, monto, moneda y la orden (`external_reference`) leídos de
  la API.
- Un monto que no coincide con el del intento de pago hace que la orden **no** se dé por pagada.
"""

import json
import uuid
from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from app.core.errors import AppError
from app.modules.payments.mercadopago import (
    MercadoPagoProvider,
    amount_for_provider,
    build_manifest,
    compute_signature,
    parse_signature_header,
)
from app.modules.payments.models import Payment
from app.modules.payments.provider import WebhookEvent
from app.modules.payments.service import _amount_matches

SECRET = "test-webhook-secret"
Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler, *, token: str = "TEST-token") -> MercadoPagoProvider:
    return MercadoPagoProvider(
        access_token=token,
        webhook_secret=SECRET,
        base_url="https://api.mercadopago.test",
        transport=httpx.MockTransport(handler),
    )


def _signed_headers(
    *, data_id: str, request_id: str = "req-1", ts: str = "1712345678"
) -> dict[str, str]:
    """Encabezados como los manda el proveedor: `x-signature: ts=...,v1=...`."""
    manifest = build_manifest(data_id=data_id, request_id=request_id, ts=ts)
    signature = compute_signature(manifest=manifest, secret=SECRET)
    return {"x-signature": f"ts={ts},v1={signature}", "x-request-id": request_id}


def test_parse_signature_header() -> None:
    assert parse_signature_header("ts=1,v1=abc") == {"ts": "1", "v1": "abc"}
    assert parse_signature_header("sin-formato") == {}


def test_amounts_are_integers_for_colombian_pesos() -> None:
    assert amount_for_provider(Decimal("129900.00")) == 129900
    assert amount_for_provider(Decimal("129900.40"), "integer") == 129900
    assert amount_for_provider(Decimal("129900.40"), "decimal") == pytest.approx(129900.4)


async def test_create_intent_sends_idempotency_key_and_returns_checkout() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "123456", "init_point": "https://mp/checkout/123456"})

    order_id = uuid.uuid4()
    intent = await _provider(handler).create_intent(
        order_id=order_id,
        amount=Decimal("129900.00"),
        currency="COP",
        description="Order MP-1",
        idempotency_key=f"order-{order_id}",
        notification_url="http://localhost:8000/api/v1/webhooks/payments/mercadopago",
    )

    assert intent.provider_reference == "123456"
    assert intent.checkout_url == "https://mp/checkout/123456"

    headers = seen["headers"]
    body = seen["body"]
    assert isinstance(headers, dict) and isinstance(body, dict)
    assert seen["path"] == "/checkout/preferences"
    assert headers["x-idempotency-key"] == f"order-{order_id}"
    assert headers["authorization"] == "Bearer TEST-token"
    assert body["external_reference"] == str(order_id)
    assert body["items"][0]["unit_price"] == 129900
    assert body["items"][0]["currency_id"] == "COP"
    assert body["notification_url"].endswith("/webhooks/payments/mercadopago")


async def test_create_intent_without_credentials_fails_with_a_stable_code() -> None:
    provider = _provider(lambda request: httpx.Response(500), token="")

    with pytest.raises(AppError) as error:
        await provider.create_intent(
            order_id=uuid.uuid4(),
            amount=Decimal("1000.00"),
            currency="COP",
            description="Order MP-2",
        )

    assert error.value.status_code == 503
    assert error.value.code == "payment_provider_not_configured"


async def test_webhook_confirms_the_payment_against_the_provider_api() -> None:
    order_id = uuid.uuid4()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "id": 999,
                "status": "approved",
                "transaction_amount": 129900,
                "currency_id": "COP",
                "external_reference": str(order_id),
            },
        )

    raw = json.dumps({"id": 5, "type": "payment", "data": {"id": "999"}}).encode()
    event = await _provider(handler).parse_webhook(raw, _signed_headers(data_id="999"))

    assert calls == ["/v1/payments/999"], "hay que consultar el pago, no creerse el aviso"
    assert event.event_id == "5"
    assert event.status == "succeeded"
    assert event.provider_reference == "999"
    assert event.amount == Decimal("129900")
    assert event.currency == "COP"
    assert event.order_id == order_id


async def test_webhook_with_a_bad_signature_never_reaches_the_provider() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    raw = json.dumps({"id": 6, "type": "payment", "data": {"id": "999"}}).encode()

    with pytest.raises(AppError) as error:
        await _provider(handler).parse_webhook(raw, {"x-signature": "ts=1,v1=deadbeef"})

    assert error.value.status_code == 401
    assert error.value.code == "invalid_signature"
    assert called is False


async def test_webhook_without_payment_id_is_rejected() -> None:
    provider = _provider(lambda request: httpx.Response(200, json={}))

    with pytest.raises(AppError) as error:
        await provider.parse_webhook(b'{"type": "payment"}', {})

    assert error.value.status_code == 400
    assert error.value.code == "invalid_payload"


def _event(*, amount: Decimal | None = None, currency: str | None = None) -> WebhookEvent:
    return WebhookEvent(
        event_id="e1",
        event_type="payment.approved",
        provider_reference="999",
        status="succeeded",
        amount=amount,
        currency=currency,
    )


def test_amount_mismatch_blocks_paying_the_order() -> None:
    payment = Payment(amount=Decimal("129900.00"), currency="COP")

    # El sandbox no informa el monto: no hay nada que comparar y se acepta.
    assert _amount_matches(_event(), payment)
    assert _amount_matches(_event(amount=Decimal("129900.00"), currency="COP"), payment)
    assert not _amount_matches(_event(amount=Decimal("1.00"), currency="COP"), payment)
    assert not _amount_matches(_event(amount=Decimal("129900.00"), currency="USD"), payment)
