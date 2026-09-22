"""Endpoints del módulo de vendedores."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.identity.deps import get_current_user, require_roles
from app.modules.identity.models import User, UserRole
from app.modules.sellers.models import Store, StoreStatus
from app.modules.sellers.schemas import StoreCreate, StoreOut, StoreUpdate
from app.modules.sellers.service import SellerService

router = APIRouter(tags=["sellers"])


def get_seller_service(session: AsyncSession = Depends(get_session)) -> SellerService:
    return SellerService(session)


@router.post("/sellers/me", response_model=StoreOut, status_code=status.HTTP_201_CREATED)
async def create_store(
    data: StoreCreate,
    user: User = Depends(get_current_user),
    service: SellerService = Depends(get_seller_service),
) -> Store:
    """Solicita la creación de la tienda (queda pendiente de aprobación del admin)."""
    return await service.apply(user.id, data)


@router.get("/sellers/me", response_model=StoreOut)
async def get_my_store(
    user: User = Depends(get_current_user),
    service: SellerService = Depends(get_seller_service),
) -> Store:
    return await service.get_my_store(user.id)


@router.patch("/sellers/me", response_model=StoreOut)
async def update_my_store(
    data: StoreUpdate,
    user: User = Depends(get_current_user),
    service: SellerService = Depends(get_seller_service),
) -> Store:
    return await service.update_store(user.id, data)


# ---------- Admin ----------


@router.get("/sellers", response_model=list[StoreOut])
async def list_stores(
    status_filter: StoreStatus | None = None,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: SellerService = Depends(get_seller_service),
) -> list[Store]:
    return await service.list_stores(status_filter)


@router.post("/sellers/{store_id}/approve", response_model=StoreOut)
async def approve_store(
    store_id: uuid.UUID,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: SellerService = Depends(get_seller_service),
) -> Store:
    return await service.approve(store_id)


@router.post("/sellers/{store_id}/reject", response_model=StoreOut)
async def reject_store(
    store_id: uuid.UUID,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: SellerService = Depends(get_seller_service),
) -> Store:
    return await service.reject(store_id)
