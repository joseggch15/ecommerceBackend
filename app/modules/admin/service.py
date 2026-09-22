"""Lógica de administración: moderación, métricas y auditoría.

Toda acción de moderación deja una entrada en `admin_actions` (quién, qué, sobre
qué y por qué) y mueve el estado del recurso. Ocultar una reseña **recalcula** la
reputación del producto y de la tienda.
"""

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.admin.models import AdminAction
from app.modules.admin.schemas import AdminActionOut, MetricsOut, StoreSalesOut
from app.modules.catalog.models import Product, ProductStatus
from app.modules.identity.models import User
from app.modules.orders.models import Order, SellerOrder
from app.modules.orders.models import PaymentStatus as OrderPaymentStatus
from app.modules.reviews.models import Review
from app.modules.reviews.repository import ReviewRepository
from app.modules.sellers.models import Store, StoreStatus

TWO_PLACES = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _action_out(action: AdminAction) -> AdminActionOut:
    return AdminActionOut(
        id=action.id,
        admin_user_id=action.admin_user_id,
        action=action.action,
        target_type=action.target_type,
        target_id=action.target_id,
        reason=action.reason,
        data=action.data,
        created_at=action.created_at,
    )


class AdminService:
    """Moderación con auditoría y tablero de métricas."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._reviews = ReviewRepository(session)

    async def moderate_product(
        self,
        admin_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        suspend: bool,
        reason: str | None = None,
    ) -> AdminActionOut:
        """Suspende (pausa) o restaura un producto."""
        product = (
            await self._session.execute(
                select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if product is None:
            raise AppError(404, "product_not_found", "Product not found.")

        product.status = ProductStatus.PAUSED if suspend else ProductStatus.ACTIVE
        action = await self._record(
            admin_id,
            "product.suspend" if suspend else "product.restore",
            "product",
            product.id,
            reason,
            {"title": product.title, "status": product.status.value},
        )
        await self._session.commit()
        return _action_out(action)

    async def moderate_store(
        self,
        admin_id: uuid.UUID,
        store_id: uuid.UUID,
        *,
        suspend: bool,
        reason: str | None = None,
    ) -> AdminActionOut:
        """Suspende o restaura (aprueba) una tienda."""
        store = (
            await self._session.execute(
                select(Store).where(Store.id == store_id, Store.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if store is None:
            raise AppError(404, "store_not_found", "Store not found.")

        store.status = StoreStatus.SUSPENDED if suspend else StoreStatus.APPROVED
        action = await self._record(
            admin_id,
            "store.suspend" if suspend else "store.restore",
            "store",
            store.id,
            reason,
            {"name": store.name, "status": store.status.value},
        )
        await self._session.commit()
        return _action_out(action)

    async def moderate_review(
        self,
        admin_id: uuid.UUID,
        review_id: uuid.UUID,
        *,
        hide: bool,
        reason: str | None = None,
    ) -> AdminActionOut:
        """Oculta o republica una reseña y recalcula la reputación."""
        review: Review | None = await self._reviews.get_by_id(review_id)
        if review is None:
            raise AppError(404, "review_not_found", "Review not found.")

        review.is_published = not hide
        await self._reviews.recompute_product(review.product_id)
        await self._reviews.recompute_store(review.store_id)

        action = await self._record(
            admin_id,
            "review.hide" if hide else "review.publish",
            "review",
            review.id,
            reason,
            {"rating": review.rating, "product_id": str(review.product_id)},
        )
        await self._session.commit()
        return _action_out(action)

    async def list_actions(self, *, limit: int = 50) -> list[AdminActionOut]:
        """Libro de auditoría, más recientes primero."""
        rows = await self._session.execute(
            select(AdminAction).order_by(AdminAction.created_at.desc()).limit(limit)
        )
        return [_action_out(row) for row in rows.scalars().all()]

    async def metrics(self) -> MetricsOut:
        """Tablero: GMV y comisión de órdenes pagadas, estados y top vendedores."""
        users = int((await self._session.scalar(select(func.count(User.id)))) or 0)
        stores = int(
            (
                await self._session.scalar(
                    select(func.count(Store.id)).where(Store.deleted_at.is_(None))
                )
            )
            or 0
        )
        products = int(
            (
                await self._session.scalar(
                    select(func.count(Product.id)).where(
                        Product.deleted_at.is_(None), Product.status == ProductStatus.ACTIVE
                    )
                )
            )
            or 0
        )

        status_rows = await self._session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status)
        )
        orders_by_status = {status.value: int(count) for status, count in status_rows.all()}

        paid = OrderPaymentStatus.PAID
        gmv = _money(
            Decimal(
                str(
                    await self._session.scalar(
                        select(func.coalesce(func.sum(Order.total), 0)).where(
                            Order.payment_status == paid
                        )
                    )
                    or 0
                )
            )
        )
        commission = _money(
            Decimal(
                str(
                    await self._session.scalar(
                        select(func.coalesce(func.sum(SellerOrder.commission_amount), 0))
                        .join(Order, Order.id == SellerOrder.order_id)
                        .where(Order.payment_status == paid)
                    )
                    or 0
                )
            )
        )

        top_rows = await self._session.execute(
            select(SellerOrder.store_id, func.sum(SellerOrder.subtotal))
            .join(Order, Order.id == SellerOrder.order_id)
            .where(Order.payment_status == paid)
            .group_by(SellerOrder.store_id)
            .order_by(func.sum(SellerOrder.subtotal).desc())
            .limit(5)
        )
        top_stores = [
            StoreSalesOut(store_id=store_id, sales=_money(Decimal(str(sales))))
            for store_id, sales in top_rows.all()
        ]

        return MetricsOut(
            users=users,
            stores=stores,
            products=products,
            orders_by_status=orders_by_status,
            gmv=gmv,
            commission=commission,
            top_stores=top_stores,
        )

    async def _record(
        self,
        admin_id: uuid.UUID,
        action: str,
        target_type: str,
        target_id: uuid.UUID | None,
        reason: str | None,
        data: dict[str, object],
    ) -> AdminAction:
        """Guarda una entrada de auditoría (confirma el servicio llamante)."""
        entry = AdminAction(
            admin_user_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            data=data,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
