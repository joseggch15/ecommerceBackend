"""Endpoints del módulo de órdenes (checkout, compras y ventas)."""

import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.orders.models import SellerOrderStatus
from app.modules.orders.schemas import (
    CheckoutRequest,
    OrderListOut,
    OrderOut,
    SellerOrderListOut,
    SellerOrderOut,
)
from app.modules.orders.service import OrderService

router = APIRouter(tags=["orders"])


def get_order_service(session: AsyncSession = Depends(get_session)) -> OrderService:
    return OrderService(session)


@router.post("/orders", response_model=OrderOut, status_code=201)
async def checkout(
    data: CheckoutRequest,
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    """Convierte el carrito en una orden.

    El comprador paga una sola vez por toda la orden; cada vendedor recibe su
    sub-orden con su comisión y su monto a liquidar. Usa el header
    `Idempotency-Key` para no duplicar la orden si el cliente reintenta.
    """
    return await service.checkout(user.id, data, idempotency_key)


@router.get("/orders", response_model=OrderListOut)
async def list_orders(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderListOut:
    """Mis compras (paginación por cursor)."""
    return await service.list_orders(user.id, limit=limit, cursor=cursor)


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    """Detalle de una orden propia (con sus sub-órdenes y líneas)."""
    return await service.get_order(order_id, user_id=user.id)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderOut:
    """Cancela una orden pendiente de pago y libera el stock reservado."""
    return await service.cancel(order_id, user_id=user.id)


@router.get("/seller/orders", response_model=SellerOrderListOut)
async def list_store_sales(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> SellerOrderListOut:
    """Ventas (sub-órdenes) de mi tienda, con su comisión y monto a liquidar."""
    return await service.list_store_sales(user.id, limit=limit, cursor=cursor)


@router.patch("/seller/orders/{seller_order_id}/status", response_model=SellerOrderOut)
async def update_sale_status(
    seller_order_id: uuid.UUID,
    status: SellerOrderStatus,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> SellerOrderOut:
    """Avanza el estado de una venta: processing → shipped → delivered."""
    return await service.update_seller_order_status(user.id, seller_order_id, status)
