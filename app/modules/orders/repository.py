"""Repositorios del módulo de órdenes."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import Order, OrderItem, OrderStatus, SellerOrder

# Estados de la orden en los que la venta **cuenta**: pagada y completada. Un reembolso deja la
# orden en `refunded` y sus unidades dejan de contar (el dinero volvió al comprador).
SOLD_ORDER_STATUSES: tuple[OrderStatus, ...] = (OrderStatus.PAID, OrderStatus.COMPLETED)


def paid_units_subquery(product_id_column: Any) -> Any:
    """Subconsulta escalar con las unidades vendidas de un producto.

    Suma `order_items.quantity` de las órdenes pagadas (o completadas). Se resuelve con una
    subconsulta correlacionada —igual que el precio mínimo o la miniatura de la búsqueda— en vez de
    con un `JOIN` + `GROUP BY`, para que el listado no cambie de forma ni de orden.

    `product_id_column` es la columna con la que se correlaciona: `Product.id` en la búsqueda, o un
    identificador concreto cuando se pregunta por un solo producto.
    """

    return (
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .select_from(OrderItem)
        .join(SellerOrder, OrderItem.seller_order_id == SellerOrder.id)
        .join(Order, SellerOrder.order_id == Order.id)
        .where(
            OrderItem.product_id == product_id_column,
            Order.status.in_(SOLD_ORDER_STATUSES),
        )
        .scalar_subquery()
    )


class OrderRepository:
    """Acceso a órdenes y sub-órdenes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        return order

    async def add_seller_order(self, seller_order: SellerOrder) -> SellerOrder:
        self._session.add(seller_order)
        await self._session.flush()
        return seller_order

    async def add_item(self, item: OrderItem) -> OrderItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        result = await self._session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, user_id: uuid.UUID, key: str) -> Order | None:
        result = await self._session.execute(
            select(Order).where(Order.user_id == user_id, Order.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def sold_count_for_product(self, product_id: uuid.UUID) -> int:
        """Unidades vendidas de un producto (solo órdenes pagadas o completadas)."""
        result = await self._session.execute(select(paid_units_subquery(product_id)))
        return int(result.scalar_one() or 0)

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int, cursor: tuple[datetime, uuid.UUID] | None
    ) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit)
        )
        if cursor is not None:
            created_at, order_id = cursor
            stmt = stmt.where(
                or_(
                    Order.created_at < created_at,
                    (Order.created_at == created_at) & (Order.id < order_id),
                )
            )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_seller_orders(self, order_id: uuid.UUID) -> list[SellerOrder]:
        result = await self._session.execute(
            select(SellerOrder)
            .where(SellerOrder.order_id == order_id)
            .order_by(SellerOrder.created_at)
        )
        return list(result.scalars().all())

    async def list_items(self, seller_order_ids: list[uuid.UUID]) -> list[OrderItem]:
        if not seller_order_ids:
            return []
        result = await self._session.execute(
            select(OrderItem)
            .where(OrderItem.seller_order_id.in_(seller_order_ids))
            .order_by(OrderItem.created_at)
        )
        return list(result.scalars().all())

    async def list_seller_orders_by_store(
        self,
        store_id: uuid.UUID,
        *,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None,
    ) -> list[SellerOrder]:
        stmt = (
            select(SellerOrder)
            .where(SellerOrder.store_id == store_id)
            .order_by(SellerOrder.created_at.desc(), SellerOrder.id.desc())
            .limit(limit)
        )
        if cursor is not None:
            created_at, seller_order_id = cursor
            stmt = stmt.where(
                or_(
                    SellerOrder.created_at < created_at,
                    (SellerOrder.created_at == created_at) & (SellerOrder.id < seller_order_id),
                )
            )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_seller_order(self, seller_order_id: uuid.UUID) -> SellerOrder | None:
        result = await self._session.execute(
            select(SellerOrder).where(SellerOrder.id == seller_order_id)
        )
        return result.scalar_one_or_none()
