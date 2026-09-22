"""Modelos ORM del módulo de órdenes.

Una **orden** (`orders`) es la compra completa del comprador y se paga una sola
vez. Se divide en **sub-órdenes por vendedor** (`seller_orders`), cada una con su
estado de preparación/envío, sus totales y su comisión. Las **líneas**
(`order_items`) cuelgan de la sub-orden y guardan una foto (snapshot) de lo
comprado (título, SKU, precio, moneda y comisión del momento).
"""

import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class OrderStatus(enum.StrEnum):
    """Estado de la orden completa."""

    PENDING = "pending"  # esperando pago
    PAID = "paid"  # pagada
    COMPLETED = "completed"  # todas las sub-órdenes entregadas
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(enum.StrEnum):
    """Estado del pago (lo gobierna el módulo de pagos, Fase 7)."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class SellerOrderStatus(enum.StrEnum):
    """Estado de preparación/envío/entrega de la sub-orden de un vendedor."""

    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Compra del comprador (un solo pago por toda la orden)."""

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_order_idempotency"),)

    order_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=False, values_callable=enum_values),
        nullable=False,
        default=OrderStatus.PENDING,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    discount_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class SellerOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Sub-orden de un vendedor dentro de una orden."""

    __tablename__ = "seller_orders"
    __table_args__ = (UniqueConstraint("order_id", "store_id", name="uq_seller_order_store"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    status: Mapped[SellerOrderStatus] = mapped_column(
        Enum(
            SellerOrderStatus,
            name="seller_order_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=SellerOrderStatus.PENDING,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    commission_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    payout_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )


class OrderItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Línea de una sub-orden, con snapshot de lo comprado."""

    __tablename__ = "order_items"

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    product_title: Mapped[str] = mapped_column(String(200), nullable=False)
    variant_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
