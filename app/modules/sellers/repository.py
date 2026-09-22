"""Repositorios del módulo de vendedores."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sellers.models import Store, StoreStatus


class StoreRepository:
    """Acceso a la tabla de tiendas (respeta el borrado lógico)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user(self, user_id: uuid.UUID) -> Store | None:
        result = await self._session.execute(
            select(Store).where(Store.user_id == user_id, Store.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, store_id: uuid.UUID) -> Store | None:
        result = await self._session.execute(
            select(Store).where(Store.id == store_id, Store.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Store | None:
        result = await self._session.execute(
            select(Store).where(Store.slug == slug, Store.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def add(self, store: Store) -> Store:
        self._session.add(store)
        await self._session.flush()
        return store

    async def list(self, status: StoreStatus | None = None) -> list[Store]:
        stmt = select(Store).where(Store.deleted_at.is_(None)).order_by(Store.created_at)
        if status is not None:
            stmt = stmt.where(Store.status == status)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
