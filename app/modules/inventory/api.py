"""Endpoints del módulo de inventario."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.identity.deps import require_roles
from app.modules.identity.models import User, UserRole
from app.modules.inventory.models import InventoryItem
from app.modules.inventory.schemas import InventoryItemOut, ReserveRequest, StockAdjustRequest
from app.modules.inventory.service import InventoryService

router = APIRouter(tags=["inventory"])


def get_inventory_service(session: AsyncSession = Depends(get_session)) -> InventoryService:
    return InventoryService(session)


@router.get("/inventory/items/{variant_id}", response_model=InventoryItemOut)
async def get_item(
    variant_id: uuid.UUID,
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItem:
    return await service.get_item(variant_id)


@router.post("/inventory/items/{variant_id}/adjust", response_model=InventoryItemOut)
async def adjust(
    variant_id: uuid.UUID,
    data: StockAdjustRequest,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItem:
    return await service.adjust(variant_id, data.delta, data.reason)


@router.post("/inventory/items/{variant_id}/reserve", response_model=InventoryItemOut)
async def reserve(
    variant_id: uuid.UUID,
    data: ReserveRequest,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItem:
    return await service.reserve(variant_id, data.quantity)


@router.post("/inventory/items/{variant_id}/release", response_model=InventoryItemOut)
async def release(
    variant_id: uuid.UUID,
    data: ReserveRequest,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryItem:
    return await service.release(variant_id, data.quantity)
