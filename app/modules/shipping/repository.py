"""Repositorios del módulo de envíos."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shipping.models import Shipment, ShipmentEvent


class ShipmentRepository:
    """Acceso a envíos y sus eventos de seguimiento."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, shipment: Shipment) -> Shipment:
        self._session.add(shipment)
        await self._session.flush()
        return shipment

    async def get_by_id(self, shipment_id: uuid.UUID) -> Shipment | None:
        result = await self._session.execute(select(Shipment).where(Shipment.id == shipment_id))
        return result.scalar_one_or_none()

    async def get_by_seller_order(self, seller_order_id: uuid.UUID) -> Shipment | None:
        result = await self._session.execute(
            select(Shipment).where(Shipment.seller_order_id == seller_order_id)
        )
        return result.scalar_one_or_none()

    async def list_by_seller_orders(self, seller_order_ids: list[uuid.UUID]) -> list[Shipment]:
        if not seller_order_ids:
            return []
        result = await self._session.execute(
            select(Shipment)
            .where(Shipment.seller_order_id.in_(seller_order_ids))
            .order_by(Shipment.created_at)
        )
        return list(result.scalars().all())

    async def add_event(self, event: ShipmentEvent) -> ShipmentEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_events(self, shipment_id: uuid.UUID) -> list[ShipmentEvent]:
        result = await self._session.execute(
            select(ShipmentEvent)
            .where(ShipmentEvent.shipment_id == shipment_id)
            .order_by(ShipmentEvent.occurred_at, ShipmentEvent.created_at)
        )
        return list(result.scalars().all())
