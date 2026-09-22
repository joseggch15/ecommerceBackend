"""Modelos ORM del módulo de envíos.

Cada **sub-orden de vendedor** (`seller_orders`) tiene su propio envío: puede
salir de otra bodega, con otra transportadora y otra guía. `shipment_events`
guarda la línea de tiempo del seguimiento.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class ShipmentStatus(enum.StrEnum):
    """Estado del envío."""

    PENDING = "pending"  # el vendedor aún no lo prepara
    READY = "ready"  # preparado, listo para entregar a la transportadora
    SHIPPED = "shipped"  # entregado a la transportadora
    IN_TRANSIT = "in_transit"  # en camino
    DELIVERED = "delivered"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class Shipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Envío de una sub-orden (uno por vendedor)."""

    __tablename__ = "shipments"

    seller_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seller_orders.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(
            ShipmentStatus,
            name="shipment_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=ShipmentStatus.PENDING,
    )
    carrier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    tracking_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShipmentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Evento de seguimiento del envío (línea de tiempo)."""

    __tablename__ = "shipment_events"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(
            ShipmentStatus,
            name="shipment_event_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
