"""Lógica de negocio del módulo de pagos.

El comprador paga **una sola vez por la orden completa**. Cada webhook del
proveedor se guarda y se aplica **una sola vez** (`payment_events` con
`UNIQUE(provider, provider_event_id)`), de modo que un reenvío no duplica el
efecto. La firma HMAC-SHA256 se verifica antes de tocar nada.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.orders.models import Order, OrderStatus
from app.modules.orders.models import PaymentStatus as OrderPaymentStatus
from app.modules.orders.repository import OrderRepository
from app.modules.payments.models import Payment, PaymentEvent, PaymentStatus
from app.modules.payments.provider import (
    SandboxPaymentProvider,
    WebhookEvent,
    get_provider,
    sign_payload,
)
from app.modules.payments.repository import PaymentRepository
from app.modules.payments.schemas import PaymentOut, WebhookAckOut

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

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
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

        if idempotency_key:
            existing = await self._payments.get_by_idempotency_key(order.id, idempotency_key)
            if existing is not None:
                return _payment_out(existing)

        provider = get_provider(settings.PAYMENT_PROVIDER)
        intent = provider.create_intent(
            order_id=order.id,
            amount=order.total,
            currency=order.currency,
            description=f"Order {order.order_number}",
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
                idempotency_key=idempotency_key,
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
        self, *, provider_name: str, raw_body: bytes, signature: str | None
    ) -> WebhookAckOut:
        """Verifica, guarda y aplica un webhook (idempotente por evento)."""
        provider = get_provider(provider_name)
        event = provider.parse_webhook(raw_body, signature)

        if await self._payments.get_event(provider_name, event.event_id) is not None:
            return WebhookAckOut(received=True, duplicate=True)

        payment = await self._payments.get_by_reference(event.provider_reference)
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
            signature=sign_payload(raw_body),
        )

        refreshed = await self._payments.get_by_id(payment_id)
        if refreshed is None:
            raise AppError(404, "payment_not_found", "Payment not found.")
        return _payment_out(refreshed)

    # ---------- Internos ----------

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
            payment.paid_at = datetime.now(UTC)
            payment.failure_reason = None
            if order is not None:
                order.payment_status = OrderPaymentStatus.PAID
                if order.status == OrderStatus.PENDING:
                    order.status = OrderStatus.PAID
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
