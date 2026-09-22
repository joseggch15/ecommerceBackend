"""Repositorios del módulo de pagos."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import Payment, PaymentEvent


class PaymentRepository:
    """Acceso a intentos de pago y eventos de webhook."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> Payment:
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        result = await self._session.execute(select(Payment).where(Payment.id == payment_id))
        return result.scalar_one_or_none()

    async def get_by_reference(self, provider_reference: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.provider_reference == provider_reference)
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, order_id: uuid.UUID, idempotency_key: str
    ) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(
                Payment.order_id == order_id, Payment.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def list_by_order(self, order_id: uuid.UUID) -> list[Payment]:
        result = await self._session.execute(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at)
        )
        return list(result.scalars().all())

    async def add_event(self, event: PaymentEvent) -> PaymentEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_event(self, provider: str, provider_event_id: str) -> PaymentEvent | None:
        result = await self._session.execute(
            select(PaymentEvent).where(
                PaymentEvent.provider == provider,
                PaymentEvent.provider_event_id == provider_event_id,
            )
        )
        return result.scalar_one_or_none()
