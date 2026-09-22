"""Endpoints del módulo de promociones (cupones de descuento)."""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.identity.deps import get_current_user, require_roles
from app.modules.identity.models import User, UserRole
from app.modules.promotions.schemas import (
    CouponCreate,
    CouponListOut,
    CouponOut,
    CouponValidateIn,
    CouponValidateOut,
)
from app.modules.promotions.service import PromotionService

router = APIRouter(tags=["promotions"])


def get_promotion_service(session: AsyncSession = Depends(get_session)) -> PromotionService:
    return PromotionService(session)


@router.post("/coupons", response_model=CouponOut, status_code=status.HTTP_201_CREATED)
async def create_coupon(
    data: CouponCreate,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: PromotionService = Depends(get_promotion_service),
) -> CouponOut:
    """Crea un cupón (solo admin)."""
    return await service.create_coupon(data)


@router.get("/coupons", response_model=CouponListOut)
async def list_coupons(
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: PromotionService = Depends(get_promotion_service),
) -> CouponListOut:
    """Lista los cupones (solo admin)."""
    return CouponListOut(items=await service.list_coupons())


@router.post("/coupons/{coupon_id}/deactivate", response_model=CouponOut)
async def deactivate_coupon(
    coupon_id: uuid.UUID,
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    service: PromotionService = Depends(get_promotion_service),
) -> CouponOut:
    """Desactiva un cupón (solo admin)."""
    return await service.deactivate(coupon_id)


@router.post("/coupons/validate", response_model=CouponValidateOut)
async def validate_coupon(
    data: CouponValidateIn,
    user: User = Depends(get_current_user),
    service: PromotionService = Depends(get_promotion_service),
) -> CouponValidateOut:
    """Vista previa del descuento del cupón sobre el carrito actual (no lo consume)."""
    subtotal = await service.cart_subtotal(user.id)
    return await service.preview(data.code, user.id, subtotal)
