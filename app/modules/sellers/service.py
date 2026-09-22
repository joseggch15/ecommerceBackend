"""Lógica de negocio del módulo de vendedores."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.sellers.models import Store, StoreStatus
from app.modules.sellers.repository import StoreRepository
from app.modules.sellers.schemas import StoreCreate, StoreUpdate
from app.shared.text import slugify


class SellerService:
    """Casos de uso de la tienda del vendedor y su aprobación."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._stores = StoreRepository(session)

    async def apply(self, user_id: uuid.UUID, data: StoreCreate) -> Store:
        existing = await self._stores.get_by_user(user_id)
        if existing is not None:
            raise AppError(409, "store_already_exists", "You already have a store.")

        store = Store(
            user_id=user_id,
            name=data.name,
            slug=await self._unique_slug(data.name),
            description=data.description,
        )
        await self._stores.add(store)
        await self._session.commit()
        return store

    async def get_my_store(self, user_id: uuid.UUID) -> Store:
        store = await self._stores.get_by_user(user_id)
        if store is None:
            raise AppError(404, "store_not_found", "You do not have a store yet.")
        return store

    async def update_store(self, user_id: uuid.UUID, data: StoreUpdate) -> Store:
        store = await self.get_my_store(user_id)

        if data.name is not None:
            store.name = data.name
            store.slug = await self._unique_slug(data.name, exclude_id=store.id)
        if data.description is not None:
            store.description = data.description

        await self._session.commit()
        return store

    async def list_stores(self, status: StoreStatus | None) -> list[Store]:
        return await self._stores.list(status)

    async def approve(self, store_id: uuid.UUID) -> Store:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise AppError(404, "store_not_found", "Store not found.")
        if store.status != StoreStatus.PENDING:
            raise AppError(409, "invalid_store_status", "Only pending stores can be approved.")
        store.status = StoreStatus.APPROVED
        await self._session.commit()
        return store

    async def reject(self, store_id: uuid.UUID) -> Store:
        store = await self._stores.get_by_id(store_id)
        if store is None:
            raise AppError(404, "store_not_found", "Store not found.")
        if store.status != StoreStatus.PENDING:
            raise AppError(409, "invalid_store_status", "Only pending stores can be rejected.")
        store.status = StoreStatus.REJECTED
        await self._session.commit()
        return store

    async def _unique_slug(self, name: str, exclude_id: uuid.UUID | None = None) -> str:
        base = slugify(name)
        candidate = base
        counter = 1
        while True:
            existing = await self._stores.get_by_slug(candidate)
            if existing is None or (exclude_id is not None and existing.id == exclude_id):
                return candidate
            counter += 1
            candidate = f"{base}-{counter}"
