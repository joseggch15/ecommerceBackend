"""Lógica de negocio del módulo de pagos.

El comprador paga **una sola vez por la orden completa**. Cada webhook del
proveedor se guarda y se aplica **una sola vez** (`payment_events` con
`UNIQUE(provider, provider_event_id)`), de modo que un reenvío no duplica el
efecto. La firma HMAC-SHA256 se verifica antes de tocar nada.
"""

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.identity.models import User
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import NotificationService
from app.modules.orders.models import Order, OrderStatus
from app.modules.orders.models import PaymentStatus as OrderPaymentStatus
from app.modules.orders.repository import OrderRepository

# Se importa para que el adaptador de Mercado Pago se registre al arrancar la aplicación.
from app.modules.payments import mercadopago as _mercadopago
from app.modules.payments.models import Payment, PaymentEvent, PaymentStatus
from app.modules.payments.provider import (
    SandboxPaymentProvider,
    WebhookEvent,
    get_provider,
    sign_payload,
)
from app.modules.payments.repository import PaymentRepository
from app.modules.payments.schemas import PaymentOut, WebhookAckOut

# Pasarelas que trae el proyecto (cada adaptador se registra al importarse).
AVAILABLE_PAYMENT_PROVIDERS = frozenset(
    {SandboxPaymentProvider.name, _mercadopago.mercadopago_provider.name}
)

# Resultado informado por el proveedor -> estado del intento de pago.
STATUS_BY_OUTCOME: dict[str, PaymentStatus] = {
    "pending": PaymentStatus.PENDING,
    "processing": PaymentStatus.PROCESSING,
    "succeeded": PaymentStatus.SUCCEEDED,
    "failed": PaymentStatus.FAILED,
    "cancelled": PaymentStatus.CANCELLED,
    "refunded": PaymentStatus.REFUNDED,
}


class PaymentService:
    """Intento de pago por orden y procesamiento idempotente de webhooks."""

    def __init__(self, session: AsyncSession, redis: Redis) -> None:
        self._session = session
        self._redis = redis
        self._payments = PaymentRepository(session)
        self._orders = OrderRepository(session)

    async def create_payment(
        self, *, user_id: uuid.UUID, order_id: uuid.UUID, idempotency_key: str | None = None
    ) -> PaymentOut:
        """Crea (o reutiliza) el intento de pago de una orden pendiente."""
        order = await self._get_order(order_id, user_id)
        if order.payment_status == OrderPaymentStatus.PAID:
            raise AppError(409, "order_already_paid", "Order is already paid.")
        if order.status != OrderStatus.PENDING:
            raise AppError(409, "order_not_payable", "Order cannot be paid in its current state.")

        # Un intento en curso (doble clic, red que se cae) se devuelve tal cual: nunca dos cobros.
        # Un intento fallido no bloquea: el comprador puede volver a intentarlo con otro pago.
        in_progress = next(
            (
                candidate
                for candidate in await self._payments.list_by_order(order.id)
                if candidate.status in {PaymentStatus.PENDING, PaymentStatus.PROCESSING}
            ),
            None,
        )
        if idempotency_key is None and in_progress is not None:
            return _payment_out(in_progress)

        if idempotency_key is not None:
            existing = await self._payments.get_by_idempotency_key(order.id, idempotency_key)
            if existing is not None:
                return _payment_out(existing)

        # La clave que se manda al proveedor se deriva de la orden y del intento: reintentar no
        # reutiliza la del intento fallido y el mismo intento no crea dos cobros.
        key = idempotency_key or f"order-{order.id}-{await self._next_attempt(order.id)}"

        provider = get_provider(settings.PAYMENT_PROVIDER)
        # El proveedor avisará a esta URL cuando el pago cambie de estado (webhook firmado).
        notification_url = (
            f"{settings.API_PUBLIC_URL.rstrip('/')}{settings.API_V1_PREFIX}"
            f"/webhooks/payments/{provider.name}"
        )
        intent = await provider.create_intent(
            order_id=order.id,
            amount=order.total,
            currency=order.currency,
            description=f"Order {order.order_number}",
            idempotency_key=key,
            notification_url=notification_url,
        )

        payment = await self._payments.add(
            Payment(
                order_id=order.id,
                provider=provider.name,
                provider_reference=intent.provider_reference,
                status=PaymentStatus.PENDING,
                amount=intent.amount,
                currency=intent.currency,
                checkout_url=intent.checkout_url,
                idempotency_key=key,
            )
        )
        await self._session.commit()
        return _payment_out(payment)

    async def get_payment(self, *, user_id: uuid.UUID, payment_id: uuid.UUID) -> PaymentOut:
        return _payment_out(await self._get_payment(payment_id, user_id))

    async def list_payments(self, *, user_id: uuid.UUID, order_id: uuid.UUID) -> list[PaymentOut]:
        order = await self._get_order(order_id, user_id)
        payments = await self._payments.list_by_order(order.id)
        return [_payment_out(payment) for payment in payments]

    async def handle_webhook(
        self, *, provider_name: str, raw_body: bytes, headers: Mapping[str, str]
    ) -> WebhookAckOut:
        """Verifica, guarda y aplica un webhook (idempotente por evento)."""
        provider = get_provider(provider_name)
        event = await provider.parse_webhook(raw_body, headers)

        if await self._payments.get_event(provider_name, event.event_id) is not None:
            return WebhookAckOut(received=True, duplicate=True)

        payment = await self._payment_for_event(event)

        event_row = await self._payments.add_event(
            PaymentEvent(
                payment_id=payment.id if payment is not None else None,
                provider=provider_name,
                provider_event_id=event.event_id,
                event_type=event.event_type,
                payload=json.loads(raw_body),
            )
        )

        if payment is None:
            # Se guarda igualmente para auditoría, pero no hay nada que aplicar.
            event_row.error = "payment_not_found"
            await self._session.commit()
            return WebhookAckOut(received=True)

        await self._apply(payment, event)
        event_row.processed_at = datetime.now(UTC)
        await self._session.commit()
        return WebhookAckOut(received=True)

    async def simulate(
        self, *, user_id: uuid.UUID, payment_id: uuid.UUID, outcome: str
    ) -> PaymentOut:
        """Simula el webhook del proveedor sandbox (mismo camino que uno real)."""
        payment = await self._get_payment(payment_id, user_id)
        if payment.provider != SandboxPaymentProvider.name:
            raise AppError(409, "simulation_not_allowed", "Only sandbox payments can be simulated.")

        raw_body = SandboxPaymentProvider.build_webhook_payload(payment.provider_reference, outcome)
        await self.handle_webhook(
            provider_name=payment.provider,
            raw_body=raw_body,
            headers={"x-signature": sign_payload(raw_body)},
        )

        refreshed = await self._payments.get_by_id(payment_id)
        if refreshed is None:
            raise AppError(404, "payment_not_found", "Payment not found.")
        return _payment_out(refreshed)

    # ---------- Internos ----------

    async def _next_attempt(self, order_id: uuid.UUID) -> int:
        """Número del siguiente intento de pago de la orden (los anteriores ya están guardados)."""
        return len(await self._payments.list_by_order(order_id)) + 1

    async def _payment_for_event(self, event: WebhookEvent) -> Payment | None:
        """Localiza el intento de pago al que se refiere el evento.

        Mercado Pago avisa con el id del **pago**, que no existe cuando creamos la preferencia: la
        referencia fiable es el id de la orden (`external_reference`). Se busca el intento que
        sigue pendiente y, si el proveedor no lo trae, se cae a la referencia guardada (sandbox).
        """
        if event.order_id is not None:
            for candidate in await self._payments.list_by_order(event.order_id):
                if candidate.status in {PaymentStatus.PENDING, PaymentStatus.PROCESSING}:
                    return candidate

        return await self._payments.get_by_reference(event.provider_reference)

    async def _apply(self, payment: Payment, event: WebhookEvent) -> None:
        """Aplica el desenlace del proveedor al pago y a la orden."""
        new_status = STATUS_BY_OUTCOME.get(event.status)
        if new_status is None:
            return
        if payment.status == PaymentStatus.SUCCEEDED and new_status != PaymentStatus.REFUNDED:
            # Ya cobrado: se ignoran eventos posteriores que no sean un reembolso.
            return

        payment.status = new_status
        order = await self._orders.get_by_id(payment.order_id)

        if new_status == PaymentStatus.SUCCEEDED:
            if not _amount_matches(event, payment):
                # Una orden no se da por pagada sin comprobar el monto y la moneda que confirma el
                # proveedor: un aviso manipulado no puede marcar una orden como pagada.
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = "amount_mismatch"
                return

            payment.paid_at = datetime.now(UTC)
            payment.failure_reason = None
            if order is not None:
                order.payment_status = OrderPaymentStatus.PAID
                if order.status == OrderStatus.PENDING:
                    order.status = OrderStatus.PAID
                buyer_email = await self._session.scalar(
                    select(User.email).where(User.id == order.user_id)
                )
                await NotificationService(self._session, self._redis).notify(
                    user_id=order.user_id,
                    type=NotificationType.ORDER_PAID,
                    title=f"Pago confirmado - {order.order_number}",
                    body=f"Recibimos tu pago de {payment.amount} {payment.currency}.",
                    data={"order_id": str(order.id)},
                    email_to=buyer_email,
                )
        elif new_status == PaymentStatus.FAILED:
            payment.failure_reason = event.failure_reason or "Payment failed."
        elif new_status == PaymentStatus.REFUNDED:
            if order is not None:
                order.payment_status = OrderPaymentStatus.REFUNDED
                order.status = OrderStatus.REFUNDED

    async def _get_order(self, order_id: uuid.UUID, user_id: uuid.UUID) -> Order:
        order = await self._orders.get_by_id(order_id)
        if order is None or order.user_id != user_id:
            raise AppError(404, "order_not_found", "Order not found.")
        return order

    async def _get_payment(self, payment_id: uuid.UUID, user_id: uuid.UUID) -> Payment:
        payment = await self._payments.get_by_id(payment_id)
        if payment is None:
            raise AppError(404, "payment_not_found", "Payment not found.")
        order = await self._orders.get_by_id(payment.order_id)
        if order is None or order.user_id != user_id:
            raise AppError(404, "payment_not_found", "Payment not found.")
        return payment


def _amount_matches(event: WebhookEvent, payment: Payment) -> bool:
    """¿El monto y la moneda que confirma el proveedor coinciden con el intento de pago?

    Si el proveedor no informa el monto (sandbox) no hay nada que comparar y se acepta; cuando lo
    informa, tiene que coincidir **exactamente** (y la moneda también, si viene).
    """
    if event.amount is None:
        return True

    if event.amount != payment.amount:
        return False

    return event.currency is None or event.currency.upper() == payment.currency.upper()


def _payment_out(payment: Payment) -> PaymentOut:
    """Convierte un intento de pago en su representación de salida."""
    return PaymentOut(
        id=payment.id,
        order_id=payment.order_id,
        provider=payment.provider,
        provider_reference=payment.provider_reference,
        status=payment.status.value,
        amount=payment.amount,
        currency=payment.currency,
        checkout_url=payment.checkout_url,
        failure_reason=payment.failure_reason,
        paid_at=payment.paid_at,
        created_at=payment.created_at,
    )
