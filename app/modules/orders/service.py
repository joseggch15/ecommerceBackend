"""Lógica de negocio del módulo de órdenes (checkout y consulta).

El checkout es **una sola transacción**: lee el carrito, valida disponibilidad,
reserva stock (con `SELECT ... FOR UPDATE`), toma la foto de precios/comisiones,
crea la orden con sus sub-órdenes por vendedor y vacía el carrito. Si algo falla,
nada se aplica (rollback) y no hay sobreventa.
"""

import base64
import secrets
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.cart.models import Cart, CartItem
from app.modules.catalog.models import (
    Category,
    Product,
    ProductStatus,
    ProductVariant,
    VariantValue,
)
from app.modules.inventory.service import InventoryService
from app.modules.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    SellerOrder,
    SellerOrderStatus,
)
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import (
    CheckoutRequest,
    OrderItemOut,
    OrderListOut,
    OrderOut,
    OrderSummaryOut,
    SellerOrderListOut,
    SellerOrderOut,
    SellerOrderSummaryOut,
)
from app.modules.promotions.models import Coupon
from app.modules.promotions.service import PromotionService, prorate
from app.modules.sellers.models import Store

TWO_PLACES = Decimal("0.01")

# Máquina de estados de la sub-orden del vendedor (preparación/envío/entrega).
SELLER_ORDER_TRANSITIONS: dict[SellerOrderStatus, set[SellerOrderStatus]] = {
    SellerOrderStatus.PENDING: {SellerOrderStatus.PROCESSING, SellerOrderStatus.CANCELLED},
    SellerOrderStatus.PROCESSING: {SellerOrderStatus.SHIPPED, SellerOrderStatus.CANCELLED},
    SellerOrderStatus.SHIPPED: {SellerOrderStatus.DELIVERED},
    SellerOrderStatus.DELIVERED: set(),
    SellerOrderStatus.CANCELLED: set(),
}


def _money(value: Decimal) -> Decimal:
    """Redondea a 2 decimales con HALF_UP (como se cobra)."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _prorate_amount(total: Decimal, weight: Decimal, part: Decimal) -> Decimal:
    """Parte proporcional de un descuento (redondeada a 2 decimales)."""
    if total <= 0 or weight <= 0:
        return Decimal("0")
    return _money(total * part / weight)


def _encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{item_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        value, item_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(value), uuid.UUID(item_id)
    except (ValueError, UnicodeDecodeError):
        raise AppError(400, "invalid_cursor", "Invalid cursor.") from None


class OrderService:
    """Checkout, consulta y cancelación de órdenes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._inventory = InventoryService(session)

    async def checkout(
        self,
        user_id: uuid.UUID,
        data: CheckoutRequest,
        idempotency_key: str | None = None,
    ) -> OrderOut:
        """Convierte el carrito del usuario en una orden (idempotente por clave)."""
        if idempotency_key:
            existing = await self._orders.get_by_idempotency_key(user_id, idempotency_key)
            if existing is not None:
                return await self.get_order(existing.id, user_id=user_id)

        lines = await self._cart_lines(user_id)
        if not lines:
            raise AppError(400, "cart_empty", "Your cart is empty.")

        currency = settings.DEFAULT_CURRENCY
        order = await self._orders.add(
            Order(
                order_number=self._new_order_number(),
                user_id=user_id,
                currency=currency,
                subtotal=Decimal("0"),
                shipping_total=Decimal("0"),
                total=Decimal("0"),
                shipping_address=data.shipping_address.model_dump(),
                notes=data.notes,
                idempotency_key=idempotency_key,
            )
        )

        grouped: dict[uuid.UUID, list[tuple[ProductVariant, Product, Category | None, int]]] = {}
        store_subtotals: dict[uuid.UUID, Decimal] = {}
        for variant, product, category, quantity in lines:
            grouped.setdefault(product.store_id, []).append((variant, product, category, quantity))
            store_subtotals[product.store_id] = store_subtotals.get(
                product.store_id, Decimal("0")
            ) + _money(variant.price * quantity)

        order_subtotal = _money(sum(store_subtotals.values(), Decimal("0")))

        # Cupón (Fase 10): se valida aquí y se prorratea entre vendedores.
        promotions: PromotionService | None = None
        coupon: Coupon | None = None
        discount = Decimal("0")
        if data.coupon_code:
            promotions = PromotionService(self._session)
            coupon, discount = await promotions.validate_for_user(
                data.coupon_code, user_id, order_subtotal
            )
        store_discounts = prorate(discount, store_subtotals)

        for store_id, store_lines in grouped.items():
            seller_order = await self._orders.add_seller_order(
                SellerOrder(
                    order_id=order.id,
                    store_id=store_id,
                    currency=currency,
                    subtotal=Decimal("0"),
                )
            )
            store_subtotal = Decimal("0")
            store_commission = Decimal("0")
            store_discount = store_discounts.get(store_id, Decimal("0"))

            for variant, product, category, quantity in store_lines:
                if product.status != ProductStatus.ACTIVE:
                    raise AppError(
                        409,
                        "product_not_available",
                        f"Product '{product.title}' is not available.",
                    )

                # Reserva atómica: si no alcanza el stock, 409 y rollback total.
                await self._inventory.reserve(variant.id, quantity, commit=False)

                line_total = _money(variant.price * quantity)
                line_discount = _prorate_amount(
                    store_discount, store_subtotals[store_id], line_total
                )
                rate = self._commission_rate(category)
                # La comisión se calcula sobre el neto (sin el descuento del cupón).
                commission = _money((line_total - line_discount) * rate / Decimal("100"))

                await self._orders.add_item(
                    OrderItem(
                        seller_order_id=seller_order.id,
                        variant_id=variant.id,
                        product_id=product.id,
                        product_title=product.title,
                        variant_label=await self._variant_label(variant.id),
                        sku=variant.sku,
                        currency=currency,
                        unit_price=variant.price,
                        quantity=quantity,
                        line_total=line_total,
                        commission_rate=rate,
                        commission_amount=commission,
                    )
                )
                store_subtotal += line_total
                store_commission += commission

            seller_order.subtotal = _money(store_subtotal)
            seller_order.discount_amount = store_discount
            seller_order.commission_amount = _money(store_commission)
            seller_order.payout_amount = _money(store_subtotal - store_discount - store_commission)

        order.subtotal = _money(order_subtotal)
        order.discount_total = _money(discount)
        order.total = _money(order.subtotal + order.shipping_total - discount)

        if coupon is not None and promotions is not None:
            await promotions.redeem(coupon, user_id, order.id, _money(discount))

        await self._clear_cart(user_id)
        await self._session.commit()

        return await self.get_order(order.id, user_id=user_id)

    async def get_order(self, order_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> OrderOut:
        """Devuelve una orden con sus sub-órdenes y líneas (solo el dueño)."""
        order = await self._orders.get_by_id(order_id)
        if order is None or (user_id is not None and order.user_id != user_id):
            raise AppError(404, "order_not_found", "Order not found.")
        return await self._build_order_out(order)

    async def list_orders(
        self, user_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> OrderListOut:
        """Lista las compras del usuario (paginación por cursor)."""
        decoded = _decode_cursor(cursor) if cursor else None
        rows = await self._orders.list_by_user(user_id, limit=limit + 1, cursor=decoded)
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = (
            _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
        )
        return OrderListOut(
            items=[
                OrderSummaryOut(
                    id=order.id,
                    order_number=order.order_number,
                    status=order.status.value,
                    payment_status=order.payment_status.value,
                    currency=order.currency,
                    total=order.total,
                    created_at=order.created_at,
                )
                for order in page
            ],
            next_cursor=next_cursor,
        )

    async def cancel(self, order_id: uuid.UUID, *, user_id: uuid.UUID) -> OrderOut:
        """Cancela una orden pendiente y libera el stock reservado."""
        order = await self._orders.get_by_id(order_id)
        if order is None or order.user_id != user_id:
            raise AppError(404, "order_not_found", "Order not found.")
        if order.status != OrderStatus.PENDING:
            raise AppError(
                409,
                "order_not_cancellable",
                "Only orders pending payment can be cancelled.",
            )

        seller_orders = await self._orders.list_seller_orders(order.id)
        items = await self._orders.list_items([seller_order.id for seller_order in seller_orders])
        for item in items:
            if item.variant_id is not None:
                await self._inventory.release(item.variant_id, item.quantity, commit=False)

        for seller_order in seller_orders:
            seller_order.status = SellerOrderStatus.CANCELLED
        order.status = OrderStatus.CANCELLED
        await self._session.commit()
        return await self._build_order_out(order)

    async def list_store_sales(
        self, user_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> SellerOrderListOut:
        """Lista las sub-órdenes (ventas) de la tienda del vendedor."""
        store_id = await self._store_id_for(user_id)
        decoded = _decode_cursor(cursor) if cursor else None
        rows = await self._orders.list_seller_orders_by_store(
            store_id, limit=limit + 1, cursor=decoded
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = (
            _encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
        )
        return SellerOrderListOut(
            items=[
                SellerOrderSummaryOut(
                    id=seller_order.id,
                    order_id=seller_order.order_id,
                    status=seller_order.status.value,
                    currency=seller_order.currency,
                    subtotal=seller_order.subtotal,
                    commission_amount=seller_order.commission_amount,
                    payout_amount=seller_order.payout_amount,
                    created_at=seller_order.created_at,
                )
                for seller_order in page
            ],
            next_cursor=next_cursor,
        )

    async def update_seller_order_status(
        self, user_id: uuid.UUID, seller_order_id: uuid.UUID, new_status: SellerOrderStatus
    ) -> SellerOrderOut:
        """Avanza el estado de preparación/envío de una sub-orden (máquina de estados)."""
        store_id = await self._store_id_for(user_id)
        seller_order = await self._orders.get_seller_order(seller_order_id)
        if seller_order is None or seller_order.store_id != store_id:
            raise AppError(404, "seller_order_not_found", "Sale not found.")

        if new_status not in SELLER_ORDER_TRANSITIONS.get(seller_order.status, set()):
            raise AppError(
                409,
                "invalid_status_transition",
                f"Cannot change status from {seller_order.status.value} to {new_status.value}.",
            )

        seller_order.status = new_status
        await self._session.commit()
        return SellerOrderOut(
            id=seller_order.id,
            store_id=seller_order.store_id,
            status=seller_order.status.value,
            currency=seller_order.currency,
            subtotal=seller_order.subtotal,
            shipping_cost=seller_order.shipping_cost,
            discount_amount=seller_order.discount_amount,
            commission_amount=seller_order.commission_amount,
            payout_amount=seller_order.payout_amount,
            items=await self._items_out([seller_order.id]),
        )

    # ---------- Internos ----------

    async def _cart_lines(
        self, user_id: uuid.UUID
    ) -> list[tuple[ProductVariant, Product, Category | None, int]]:
        """Lee el carrito del usuario con producto, categoría y cantidad."""
        result = await self._session.execute(
            select(ProductVariant, Product, Category, CartItem.quantity)
            .select_from(CartItem)
            .join(Cart, Cart.id == CartItem.cart_id)
            .join(ProductVariant, ProductVariant.id == CartItem.variant_id)
            .join(Product, Product.id == ProductVariant.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .where(Cart.user_id == user_id)
            .order_by(CartItem.created_at)
        )
        return [
            (variant, product, category, quantity)
            for variant, product, category, quantity in result.tuples().all()
        ]

    async def _clear_cart(self, user_id: uuid.UUID) -> None:
        cart_id = (
            await self._session.execute(select(Cart.id).where(Cart.user_id == user_id))
        ).scalar_one_or_none()
        if cart_id is not None:
            await self._session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))

    async def _variant_label(self, variant_id: uuid.UUID) -> str | None:
        """Etiqueta legible de la variante (valores de sus atributos)."""
        result = await self._session.execute(
            select(VariantValue.value)
            .where(VariantValue.variant_id == variant_id)
            .order_by(VariantValue.value)
        )
        values = [value for value in result.scalars().all() if value]
        return " / ".join(values) if values else None

    @staticmethod
    def _commission_rate(category: Category | None) -> Decimal:
        """Comisión efectiva: la de la categoría si existe, si no la global."""
        if category is not None and category.commission_rate is not None:
            return Decimal(category.commission_rate)
        return Decimal(settings.DEFAULT_COMMISSION_RATE)

    @staticmethod
    def _new_order_number() -> str:
        """Número legible de orden: ORD-AAAAMMDD-XXXXXX."""
        return f"ORD-{datetime.now(UTC).strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

    async def _build_order_out(self, order: Order) -> OrderOut:
        seller_orders = await self._orders.list_seller_orders(order.id)
        items = await self._orders.list_items([row.id for row in seller_orders])
        grouped: dict[uuid.UUID, list[OrderItemOut]] = {}
        for item in items:
            grouped.setdefault(item.seller_order_id, []).append(_item_out(item))

        return OrderOut(
            id=order.id,
            order_number=order.order_number,
            status=order.status.value,
            payment_status=order.payment_status.value,
            currency=order.currency,
            subtotal=order.subtotal,
            shipping_total=order.shipping_total,
            discount_total=order.discount_total,
            total=order.total,
            shipping_address=order.shipping_address,
            notes=order.notes,
            created_at=order.created_at,
            seller_orders=[
                SellerOrderOut(
                    id=seller_order.id,
                    store_id=seller_order.store_id,
                    status=seller_order.status.value,
                    currency=seller_order.currency,
                    subtotal=seller_order.subtotal,
                    shipping_cost=seller_order.shipping_cost,
                    discount_amount=seller_order.discount_amount,
                    commission_amount=seller_order.commission_amount,
                    payout_amount=seller_order.payout_amount,
                    items=grouped.get(seller_order.id, []),
                )
                for seller_order in seller_orders
            ],
        )

    async def _items_out(self, seller_order_ids: list[uuid.UUID]) -> list[OrderItemOut]:
        items = await self._orders.list_items(seller_order_ids)
        return [_item_out(item) for item in items]

    async def _store_id_for(self, user_id: uuid.UUID) -> uuid.UUID:
        result = await self._session.execute(
            select(Store.id).where(Store.user_id == user_id, Store.deleted_at.is_(None))
        )
        store_id = result.scalar_one_or_none()
        if store_id is None:
            raise AppError(403, "store_required", "You need a store to manage sales.")
        return store_id


def _item_out(item: OrderItem) -> OrderItemOut:
    """Convierte una línea de orden en su representación de salida."""
    return OrderItemOut(
        id=item.id,
        variant_id=item.variant_id,
        product_id=item.product_id,
        product_title=item.product_title,
        variant_label=item.variant_label,
        sku=item.sku,
        currency=item.currency,
        unit_price=item.unit_price,
        quantity=item.quantity,
        line_total=item.line_total,
        commission_rate=item.commission_rate,
        commission_amount=item.commission_amount,
    )
