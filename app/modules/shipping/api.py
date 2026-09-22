"""Endpoints del módulo de envíos (vendedor y comprador)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.shipping.models import ShipmentStatus
from app.modules.shipping.schemas import ShipmentCreate, ShipmentOut, ShipmentUpdate
from app.modules.shipping.service import ShipmentService

router = APIRouter(tags=["shipping"])


def get_shipment_service(session: AsyncSession = Depends(get_session)) -> ShipmentService:
    return ShipmentService(session)


@router.post(
    "/seller/orders/{seller_order_id}/shipment", response_model=ShipmentOut, status_code=201
)
async def create_shipment(
    seller_order_id: uuid.UUID,
    data: ShipmentCreate,
    user: User = Depends(get_current_user),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentOut:
    """El vendedor prepara el envío de una de sus ventas (transportadora, guía, costo)."""
    return await service.create_shipment(user.id, seller_order_id, data)


@router.patch("/seller/orders/{seller_order_id}/shipment", response_model=ShipmentOut)
async def update_shipment(
    seller_order_id: uuid.UUID,
    data: ShipmentUpdate,
    user: User = Depends(get_current_user),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentOut:
    """Actualiza transportadora, guía o costo del envío."""
    return await service.update_shipment(user.id, seller_order_id, data)


@router.get("/seller/orders/{seller_order_id}/shipment", response_model=ShipmentOut)
async def get_seller_shipment(
    seller_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentOut:
    """Envío de una venta, con su línea de tiempo."""
    return await service.get_for_seller(user.id, seller_order_id)


@router.post("/seller/orders/{seller_order_id}/shipment/status", response_model=ShipmentOut)
async def update_shipment_status(
    seller_order_id: uuid.UUID,
    status: ShipmentStatus = Query(...),
    description: str | None = Query(default=None, max_length=255),
    user: User = Depends(get_current_user),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentOut:
    """Avanza el envío: ready → shipped → in_transit → delivered (+ returned/cancelled).

    El cambio se refleja en la sub-orden y, si todas se entregan, la orden pasa a `completed`.
    """
    return await service.update_status(user.id, seller_order_id, status, description)


@router.get("/orders/{order_id}/shipments", response_model=list[ShipmentOut])
async def list_order_shipments(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ShipmentService = Depends(get_shipment_service),
) -> list[ShipmentOut]:
    """Envíos (y seguimiento) de una orden propia, uno por vendedor."""
    return await service.list_for_order(user.id, order_id)
