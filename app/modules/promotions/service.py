"""Lógica de negocio del módulo de promociones.

Un cupón se valida contra el carrito del usuario y se aplica **dentro de la
misma transacción del checkout**: el descuento se prorratea por sub-orden, la
comisión se calcula sobre el **neto** y el canje se registra con
`UNIQUE(coupon_id, order_id)` (idempotente).
"""

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.cart.models import Cart, CartItem
from app.modules.catalog.models import ProductVariant
from app.modules.promotions.models import Coupon, CouponRedemption, DiscountType
from app.modules.promotions.repository import CouponRepository
from app.modules.promotions.schemas import CouponCreate, CouponOut, CouponValidateOut

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _coupon_out(coupon: Coupon) -> CouponOut:
    return CouponOut(
        id=coupon.id,
        code=coupon.code,
        description=coupon.description,
        discount_type=coupon.discount_type.value,
        value=coupon.value,
        currency=coupon.currency,
        min_purchase=coupon.min_purchase,
        starts_at=coupon.starts_at,
        ends_at=coupon.ends_at,
        max_uses=coupon.max_uses,
        max_uses_per_user=coupon.max_uses_per_user,
        used_count=coupon.used_count,
        store_id=coupon.store_id,
        is_active=coupon.is_active,
        created_at=coupon.created_at,
    )


def discount_for(coupon: Coupon, subtotal: Decimal) -> Decimal:
    """Descuento del cupón sobre un subtotal (nunca mayor que el subtotal)."""
    if coupon.discount_type == DiscountType.PERCENT:
        raw = subtotal * coupon.value / Decimal("100")
    else:
        raw = coupon.value
    return min(_money(raw), _money(subtotal))


def prorate(total_discount: Decimal, weights: dict[uuid.UUID, Decimal]) -> dict[uuid.UUID, Decimal]:
    """Reparte el descuento en proporción a cada peso, sin perder centavos."""
    if total_discount <= 0 or not weights:
        return dict.fromkeys(weights, Decimal("0"))

    grand = _money(sum(weights.values(), Decimal("0")))
    keys = list(weights)
    shares: dict[uuid.UUID, Decimal] = {}
    assigned = Decimal("0")
    for key in keys[:-1]:
        share = _money(total_discount * weights[key] / grand) if grand > 0 else Decimal("0")
        shares[key] = share
        assigned += share
    shares[keys[-1]] = _money(total_discount - assigned)
    return shares


class PromotionService:
    """Cupones: administración, validación y canje."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._coupons = CouponRepository(session)

    async def create_coupon(self, data: CouponCreate) -> CouponOut:
        """Crea un cupón (solo admin)."""
        if await self._coupons.get_by_code(data.code) is not None:
            raise AppError(409, "coupon_exists", "A coupon with that code already exists.")
        if data.discount_type == DiscountType.PERCENT and data.value > 100:
            raise AppError(400, "invalid_coupon_value", "Percent discount cannot exceed 100.")

        coupon = await self._coupons.add(
            Coupon(
                code=data.code,
                description=data.description,
                discount_type=data.discount_type,
                value=data.value,
                currency=settings.DEFAULT_CURRENCY,
                min_purchase=data.min_purchase,
                starts_at=data.starts_at,
                ends_at=data.ends_at,
                max_uses=data.max_uses,
                max_uses_per_user=data.max_uses_per_user,
                store_id=data.store_id,
            )
        )
        await self._session.commit()
        return _coupon_out(coupon)

    async def list_coupons(self) -> list[CouponOut]:
        return [_coupon_out(coupon) for coupon in await self._coupons.list_all()]

    async def deactivate(self, coupon_id: uuid.UUID) -> CouponOut:
        coupon = await self._coupons.get_by_id(coupon_id)
        if coupon is None:
            raise AppError(404, "coupon_not_found", "Coupon not found.")
        coupon.is_active = False
        await self._session.commit()
        return _coupon_out(coupon)

    async def validate_for_user(
        self, code: str, user_id: uuid.UUID, subtotal: Decimal
    ) -> tuple[Coupon, Decimal]:
        """Valida el cupón para este usuario y subtotal; **no** lo consume."""
        coupon = await self._coupons.get_by_code(code)
        if coupon is None or not coupon.is_active:
            raise AppError(404, "coupon_not_found", "Coupon not found or inactive.")

        now = datetime.now(UTC)
        if coupon.starts_at is not None and now < coupon.starts_at:
            raise AppError(409, "coupon_not_started", "Coupon is not valid yet.")
        if coupon.ends_at is not None and now > coupon.ends_at:
            raise AppError(409, "coupon_expired", "Coupon has expired.")
        if subtotal < coupon.min_purchase:
            raise AppError(
                409,
                "min_purchase_not_met",
                f"Coupon requires a minimum purchase of {coupon.min_purchase} {coupon.currency}.",
            )
        if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
            raise AppError(409, "coupon_usage_limit", "Coupon reached its usage limit.")
        if coupon.max_uses_per_user is not None:
            used = await self._coupons.count_user_redemptions(coupon.id, user_id)
            if used >= coupon.max_uses_per_user:
                raise AppError(409, "coupon_user_limit", "You already used this coupon.")

        return coupon, discount_for(coupon, subtotal)

    async def preview(self, code: str, user_id: uuid.UUID, subtotal: Decimal) -> CouponValidateOut:
        """Vista previa del descuento sobre el carrito actual."""
        coupon, discount = await self.validate_for_user(code, user_id, subtotal)
        return CouponValidateOut(
            code=coupon.code,
            discount_type=coupon.discount_type.value,
            discount_amount=discount,
            subtotal=_money(subtotal),
            total=_money(subtotal - discount),
            currency=coupon.currency,
        )

    async def redeem(
        self, coupon: Coupon, user_id: uuid.UUID, order_id: uuid.UUID, amount: Decimal
    ) -> None:
        """Registra el canje y suma el uso (misma transacción del checkout)."""
        await self._coupons.add_redemption(
            CouponRedemption(coupon_id=coupon.id, user_id=user_id, order_id=order_id, amount=amount)
        )
        coupon.used_count += 1

    async def cart_subtotal(self, user_id: uuid.UUID) -> Decimal:
        """Subtotal del carrito del usuario (base para validar el cupón)."""
        total = await self._session.scalar(
            select(func.sum(ProductVariant.price * CartItem.quantity))
            .select_from(CartItem)
            .join(Cart, Cart.id == CartItem.cart_id)
            .join(ProductVariant, ProductVariant.id == CartItem.variant_id)
            .where(Cart.user_id == user_id)
        )
        return _money(Decimal(str(total or 0)))
