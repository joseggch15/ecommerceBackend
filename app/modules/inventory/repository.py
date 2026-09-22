"""Repositorios del módulo de inventario."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import InventoryItem, InventoryMovement


class InventoryRepository:
    """Acceso a stock y movimientos."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_variant(
        self, variant_id: uuid.UUID, *, for_update: bool = False
    ) -> InventoryItem | None:
        stmt = select(InventoryItem).where(InventoryItem.variant_id == variant_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, item: InventoryItem) -> InventoryItem:
        self._session.add(item)
        await self._session.flush()
        return item

    async def add_movement(self, movement: InventoryMovement) -> InventoryMovement:
        self._session.add(movement)
        await self._session.flush()
        return movement

    async def list_levels(
        self, variant_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """Stock de varias variantes en una consulta: `{variant_id: (total, disponible)}`.

        Las variantes que no tienen fila de inventario **no aparecen** en el diccionario: quien
        consulte debe tratarlas como 0 disponibles (no hay nada que vender).
        """
        if not variant_ids:
            return {}

        result = await self._session.execute(
            select(
                InventoryItem.variant_id, InventoryItem.quantity, InventoryItem.reserved_quantity
            ).where(InventoryItem.variant_id.in_(variant_ids))
        )
        return {
            row[0]: (row[1], row[1] - row[2])
            for row in result.all()
        }
