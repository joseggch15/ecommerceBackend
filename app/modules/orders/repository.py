"""Repositorios del módulo de órdenes."""

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import Order, OrderItem, SellerOrder


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
