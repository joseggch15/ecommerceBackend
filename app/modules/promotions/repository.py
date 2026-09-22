"""Repositorios del módulo de promociones."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.promotions.models import Coupon, CouponRedemption


class CouponRepository:
    """Acceso a cupones y canjes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, coupon: Coupon) -> Coupon:
        self._session.add(coupon)
        await self._session.flush()
        return coupon

    async def get_by_id(self, coupon_id: uuid.UUID) -> Coupon | None:
        result = await self._session.execute(select(Coupon).where(Coupon.id == coupon_id))
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Coupon | None:
        result = await self._session.execute(select(Coupon).where(Coupon.code == code.upper()))
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100) -> list[Coupon]:
        result = await self._session.execute(
            select(Coupon).order_by(Coupon.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def add_redemption(self, redemption: CouponRedemption) -> CouponRedemption:
        self._session.add(redemption)
        await self._session.flush()
        return redemption

    async def count_user_redemptions(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.coupon_id == coupon_id, CouponRedemption.user_id == user_id
            )
        )
        return int(count or 0)
