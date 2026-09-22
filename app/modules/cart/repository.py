"""Repositorios del módulo de carrito."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cart.models import Cart, CartItem


class CartRepository:
    """Acceso a carritos de usuarios registrados."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user(self, user_id: uuid.UUID) -> Cart | None:
        result = await self._session.execute(select(Cart).where(Cart.user_id == user_id))
        return result.scalar_one_or_none()

    async def add(self, cart: Cart) -> Cart:
        self._session.add(cart)
        await self._session.flush()
        return cart


class CartItemRepository:
    """Acceso a las líneas del carrito."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, cart_id: uuid.UUID, variant_id: uuid.UUID) -> CartItem | None:
        result = await self._session.execute(
            select(CartItem).where(CartItem.cart_id == cart_id, CartItem.variant_id == variant_id)
        )
        return result.scalar_one_or_none()

    async def add(self, item: CartItem) -> CartItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def delete(self, item: CartItem) -> None:
        await self._session.delete(item)

    async def delete_all(self, cart_id: uuid.UUID) -> None:
        await self._session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
