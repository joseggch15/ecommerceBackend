"""Endpoints del módulo de pagos (intentos, webhooks y simulador sandbox)."""

import uuid

from fastapi import APIRouter, Depends, Header, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.payments.schemas import PaymentOut, SandboxOutcome, WebhookAckOut
from app.modules.payments.service import PaymentService

router = APIRouter(tags=["payments"])


def get_payment_service(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> PaymentService:
    return PaymentService(session, redis)


@router.post("/orders/{order_id}/payments", response_model=PaymentOut, status_code=201)
async def create_payment(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    """Crea el intento de pago de una orden y devuelve la URL donde pagar.

    Repetir con el mismo `Idempotency-Key` devuelve el mismo intento.
    """
    return await service.create_payment(
        user_id=user.id, order_id=order_id, idempotency_key=idempotency_key
    )


@router.get("/orders/{order_id}/payments", response_model=list[PaymentOut])
async def list_payments(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
) -> list[PaymentOut]:
    """Intentos de pago de una orden propia."""
    return await service.list_payments(user_id=user.id, order_id=order_id)


@router.get("/payments/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    """Estado actual de un intento de pago."""
    return await service.get_payment(user_id=user.id, payment_id=payment_id)


@router.post("/payments/{payment_id}/simulate", response_model=PaymentOut)
async def simulate_payment(
    payment_id: uuid.UUID,
    outcome: SandboxOutcome = Query(...),
    user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
) -> PaymentOut:
    """Simula el webhook del proveedor sandbox (solo desarrollo).

    Recorre el **mismo camino** que un webhook real: firma, idempotencia y
    actualización de la orden.
    """
    return await service.simulate(user_id=user.id, payment_id=payment_id, outcome=outcome.value)


@router.post("/webhooks/payments/{provider}", response_model=WebhookAckOut)
async def payment_webhook(
    provider: str,
    request: Request,
    service: PaymentService = Depends(get_payment_service),
) -> WebhookAckOut:
    """Webhook del proveedor.

    Los encabezados se pasan completos al adaptador, que conoce su propio protocolo de firma (el
    sandbox usa `X-Signature` con HMAC-SHA256 del cuerpo; Mercado Pago usa `x-signature` +
    `x-request-id`). El cuerpo **crudo** es lo que se firma, así que se lee tal cual llega.
    """
    raw_body = await request.body()
    return await service.handle_webhook(
        provider_name=provider, raw_body=raw_body, headers=request.headers
    )
