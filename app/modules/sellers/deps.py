"""Dependencias del módulo de vendedores."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AppError
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.sellers.models import Store, StoreStatus
from app.modules.sellers.repository import StoreRepository


async def get_approved_store(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Store:
    """Resuelve la tienda aprobada del usuario actual (o lanza 403)."""
    store = await StoreRepository(session).get_by_user(user.id)
    if store is None:
        raise AppError(403, "seller_required", "You must have a store to manage products.")
    if store.status != StoreStatus.APPROVED:
        raise AppError(403, "store_not_approved", "Your store is not approved yet.")
    return store
