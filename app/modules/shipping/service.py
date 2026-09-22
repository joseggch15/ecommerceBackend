"""Lógica de negocio del módulo de envíos.

El vendedor prepara el envío de su sub-orden (transportadora, guía y costo
logístico) y lo va moviendo por la máquina de estados; cada cambio deja un
evento de seguimiento. El comprador ve los envíos de su orden con su línea de
tiempo. Al entregarse todas las sub-órdenes, la orden pasa a `completed`.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.orders.models import OrderStatus, SellerOrder, SellerOrderStatus
from app.modules.orders.repository import OrderRepository
from app.modules.sellers.models import Store
from app.modules.shipping.models import Shipment, ShipmentEvent, ShipmentStatus
from app.modules.shipping.repository import ShipmentRepository
from app.modules.shipping.schemas import (
    ShipmentCreate,
    ShipmentEventOut,
    ShipmentOut,
    ShipmentUpdate,
)

# Máquina de estados del envío.
SHIPMENT_TRANSITIONS: dict[ShipmentStatus, set[ShipmentStatus]] = {
    ShipmentStatus.PENDING: {ShipmentStatus.READY, ShipmentStatus.CANCELLED},
    ShipmentStatus.READY: {ShipmentStatus.SHIPPED, ShipmentStatus.CANCELLED},
    ShipmentStatus.SHIPPED: {
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.DELIVERED,
        ShipmentStatus.RETURNED,
    },
    ShipmentStatus.IN_TRANSIT: {ShipmentStatus.DELIVERED, ShipmentStatus.RETURNED},
    ShipmentStatus.DELIVERED: {ShipmentStatus.RETURNED},
    ShipmentStatus.RETURNED: set(),
    ShipmentStatus.CANCELLED: set(),
}


class ShipmentService:
    """Envíos por sub-orden, vistos por el vendedor y por el comprador."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._shipments = ShipmentRepository(session)
        self._orders = OrderRepository(session)

    async def create_shipment(
        self, user_id: uuid.UUID, seller_order_id: uuid.UUID, data: ShipmentCreate
    ) -> ShipmentOut:
        """El vendedor prepara el envío de una de sus ventas."""
        store_id, seller_order = await self._load_for_seller(user_id, seller_order_id)
        if await self._shipments.get_by_seller_order(seller_order.id) is not None:
            raise AppError(409, "shipment_exists", "This sale already has a shipment.")
        if seller_order.status == SellerOrderStatus.CANCELLED:
            raise AppError(409, "sale_cancelled", "Cannot ship a cancelled sale.")

        shipment = await self._shipments.add(
            Shipment(
                seller_order_id=seller_order.id,
                status=ShipmentStatus.READY,
                carrier=data.carrier,
                tracking_number=data.tracking_number,
                tracking_url=data.tracking_url,
                cost=data.cost,
                currency=seller_order.currency,
                notes=data.notes,
            )
        )
        await self._record_event(
            shipment.id, ShipmentStatus.READY, "Shipment prepared by the seller."
        )
        await self._session.commit()
        return await self._out(shipment, store_id)

    async def update_shipment(
        self, user_id: uuid.UUID, seller_order_id: uuid.UUID, data: ShipmentUpdate
    ) -> ShipmentOut:
        """Actualiza transportadora, guía o costo del envío."""
        store_id, seller_order = await self._load_for_seller(user_id, seller_order_id)
        shipment = await self._require_shipment(seller_order.id)

        if data.carrier is not None:
            shipment.carrier = data.carrier
        if data.tracking_number is not None:
            shipment.tracking_number = data.tracking_number
        if data.tracking_url is not None:
            shipment.tracking_url = data.tracking_url
        if data.cost is not None:
            shipment.cost = data.cost
        if data.notes is not None:
            shipment.notes = data.notes

        await self._session.commit()
        return await self._out(shipment, store_id)

    async def update_status(
        self,
        user_id: uuid.UUID,
        seller_order_id: uuid.UUID,
        new_status: ShipmentStatus,
        description: str | None = None,
    ) -> ShipmentOut:
        """Avanza el estado del envío, deja el evento y sincroniza la sub-orden."""
        store_id, seller_order = await self._load_for_seller(user_id, seller_order_id)
        shipment = await self._require_shipment(seller_order.id)

        if new_status not in SHIPMENT_TRANSITIONS.get(shipment.status, set()):
            raise AppError(
                409,
                "invalid_status_transition",
                f"Cannot change shipment from {shipment.status.value} to {new_status.value}.",
            )

        shipment.status = new_status
        now = datetime.now(UTC)
        if new_status in {ShipmentStatus.SHIPPED, ShipmentStatus.IN_TRANSIT}:
            if shipment.shipped_at is None:
                shipment.shipped_at = now
        if new_status == ShipmentStatus.DELIVERED:
            shipment.delivered_at = now

        await self._record_event(shipment.id, new_status, description)
        await self._sync_seller_order(seller_order, new_status)
        await self._session.commit()
        return await self._out(shipment, store_id)

    async def get_for_seller(self, user_id: uuid.UUID, seller_order_id: uuid.UUID) -> ShipmentOut:
        """Envío de una venta, visto por su vendedor."""
        store_id, seller_order = await self._load_for_seller(user_id, seller_order_id)
        shipment = await self._require_shipment(seller_order.id)
        return await self._out(shipment, store_id)

    async def list_for_order(self, user_id: uuid.UUID, order_id: uuid.UUID) -> list[ShipmentOut]:
        """Envíos de una orden propia (vista del comprador)."""
        order = await self._orders.get_by_id(order_id)
        if order is None or order.user_id != user_id:
            raise AppError(404, "order_not_found", "Order not found.")

        seller_orders = await self._orders.list_seller_orders(order.id)
        by_id = {seller_order.id: seller_order.store_id for seller_order in seller_orders}
        shipments = await self._shipments.list_by_seller_orders(list(by_id))
        return [
            await self._out(shipment, by_id[shipment.seller_order_id]) for shipment in shipments
        ]

    # ---------- Internos ----------

    async def _load_for_seller(
        self, user_id: uuid.UUID, seller_order_id: uuid.UUID
    ) -> tuple[uuid.UUID, SellerOrder]:
        """Comprueba que la venta pertenece a la tienda del usuario."""
        store_id = await self._store_id_for(user_id)
        seller_order = await self._orders.get_seller_order(seller_order_id)
        if seller_order is None or seller_order.store_id != store_id:
            raise AppError(404, "seller_order_not_found", "Sale not found.")
        return store_id, seller_order

    async def _store_id_for(self, user_id: uuid.UUID) -> uuid.UUID:
        result = await self._session.execute(
            select(Store.id).where(Store.user_id == user_id, Store.deleted_at.is_(None))
        )
        store_id = result.scalar_one_or_none()
        if store_id is None:
            raise AppError(403, "store_required", "You need a store to manage shipments.")
        return store_id

    async def _require_shipment(self, seller_order_id: uuid.UUID) -> Shipment:
        shipment = await self._shipments.get_by_seller_order(seller_order_id)
        if shipment is None:
            raise AppError(404, "shipment_not_found", "Shipment not found.")
        return shipment

    async def _record_event(
        self, shipment_id: uuid.UUID, status: ShipmentStatus, description: str | None
    ) -> None:
        await self._shipments.add_event(
            ShipmentEvent(
                shipment_id=shipment_id,
                status=status,
                description=description or status.value.replace("_", " ").capitalize(),
                occurred_at=datetime.now(UTC),
            )
        )

    async def _sync_seller_order(
        self, seller_order: SellerOrder, shipment_status: ShipmentStatus
    ) -> None:
        """Refleja el estado del envío en la sub-orden (y en la orden)."""
        if shipment_status in {ShipmentStatus.SHIPPED, ShipmentStatus.IN_TRANSIT}:
            if seller_order.status == SellerOrderStatus.PENDING:
                seller_order.status = SellerOrderStatus.PROCESSING
            if seller_order.status == SellerOrderStatus.PROCESSING:
                seller_order.status = SellerOrderStatus.SHIPPED
        elif shipment_status == ShipmentStatus.DELIVERED:
            seller_order.status = SellerOrderStatus.DELIVERED
            await self._complete_order_if_delivered(seller_order.order_id)

    async def _complete_order_if_delivered(self, order_id: uuid.UUID) -> None:
        seller_orders = await self._orders.list_seller_orders(order_id)
        if not seller_orders or not all(
            row.status == SellerOrderStatus.DELIVERED for row in seller_orders
        ):
            return
        order = await self._orders.get_by_id(order_id)
        if order is not None and order.status == OrderStatus.PAID:
            order.status = OrderStatus.COMPLETED

    async def _out(self, shipment: Shipment, store_id: uuid.UUID) -> ShipmentOut:
        events = await self._shipments.list_events(shipment.id)
        return ShipmentOut(
            id=shipment.id,
            seller_order_id=shipment.seller_order_id,
            store_id=store_id,
            status=shipment.status.value,
            carrier=shipment.carrier,
            tracking_number=shipment.tracking_number,
            tracking_url=shipment.tracking_url,
            cost=shipment.cost,
            currency=shipment.currency,
            notes=shipment.notes,
            shipped_at=shipment.shipped_at,
            delivered_at=shipment.delivered_at,
            created_at=shipment.created_at,
            events=[
                ShipmentEventOut(
                    status=event.status.value,
                    description=event.description,
                    occurred_at=event.occurred_at,
                )
                for event in events
            ],
        )
