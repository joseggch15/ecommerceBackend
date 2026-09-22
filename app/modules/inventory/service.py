"""Lógica de negocio del módulo de inventario."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.inventory.models import InventoryItem, InventoryMovement
from app.modules.inventory.repository import InventoryRepository


@dataclass(frozen=True)
class StockLevel:
    """Stock de una variante: total (`quantity`) y disponible para vender (`available`)."""

    quantity: int
    available: int


class InventoryService:
    """Gestión de stock y reservas (cero sobreventa)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._items = InventoryRepository(session)

    async def availability_for(
        self, variant_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, StockLevel]:
        """Stock de varias variantes en una consulta (para listados y fichas de producto).

        Las variantes sin fila de inventario se devuelven con 0 unidades: es más claro para quien
        pinta la interfaz que tener que inventarse el valor ausente.
        """
        levels = await self._items.list_levels(variant_ids)

        return {
            variant_id: StockLevel(
                quantity=levels.get(variant_id, (0, 0))[0],
                available=levels.get(variant_id, (0, 0))[1],
            )
            for variant_id in variant_ids
        }

    async def ensure_item(self, variant_id: uuid.UUID, initial_quantity: int = 0) -> InventoryItem:
        """Crea el item de stock de una variante si no existe (al crear la variante)."""
        item = await self._items.get_by_variant(variant_id)
        if item is None:
            item = InventoryItem(variant_id=variant_id, quantity=initial_quantity)
            await self._items.add(item)
            if initial_quantity:
                await self._record_movement(variant_id, initial_quantity, "initial")
        return item

    async def get_item(self, variant_id: uuid.UUID) -> InventoryItem:
        item = await self._items.get_by_variant(variant_id)
        if item is None:
            raise AppError(404, "inventory_not_found", "Inventory item not found.")
        return item

    async def adjust(self, variant_id: uuid.UUID, delta: int, reason: str) -> InventoryItem:
        item = await self._items.get_by_variant(variant_id, for_update=True)
        if item is None:
            raise AppError(404, "inventory_not_found", "Inventory item not found.")

        new_quantity = item.quantity + delta
        if new_quantity < item.reserved_quantity:
            raise AppError(409, "insufficient_stock", "Stock cannot go below reserved quantity.")

        item.quantity = new_quantity
        await self._record_movement(variant_id, delta, reason)
        await self._session.commit()
        return item

    async def reserve(
        self, variant_id: uuid.UUID, quantity: int, *, commit: bool = True
    ) -> InventoryItem:
        """Reserva stock de forma atómica (SELECT ... FOR UPDATE).

        Con `commit=False` se puede participar en una transacción mayor (checkout).
        """
        item = await self._items.get_by_variant(variant_id, for_update=True)
        if item is None:
            raise AppError(404, "inventory_not_found", "Inventory item not found.")

        if item.available < quantity:
            raise AppError(409, "insufficient_stock", "Not enough stock available.")

        item.reserved_quantity += quantity
        await self._record_movement(variant_id, -quantity, "reservation")
        if commit:
            await self._session.commit()
        else:
            await self._session.flush()
        return item

    async def release(
        self, variant_id: uuid.UUID, quantity: int, *, commit: bool = True
    ) -> InventoryItem:
        """Libera una reserva previamente hecha.

        Con `commit=False` se puede participar en una transacción mayor (cancelación).
        """
        item = await self._items.get_by_variant(variant_id, for_update=True)
        if item is None:
            raise AppError(404, "inventory_not_found", "Inventory item not found.")

        if item.reserved_quantity < quantity:
            raise AppError(409, "invalid_release", "Cannot release more than reserved.")

        item.reserved_quantity -= quantity
        await self._record_movement(variant_id, quantity, "release")
        if commit:
            await self._session.commit()
        else:
            await self._session.flush()
        return item

    async def _record_movement(self, variant_id: uuid.UUID, delta: int, reason: str) -> None:
        await self._items.add_movement(
            InventoryMovement(variant_id=variant_id, delta=delta, reason=reason)
        )
