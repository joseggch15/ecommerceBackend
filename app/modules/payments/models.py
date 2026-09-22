"""Modelos ORM del módulo de pagos.

- **`payments`**: intento de pago de una orden (el comprador paga una sola vez
  por la orden completa; puede haber reintentos).
- **`payment_events`**: cada webhook recibido del proveedor, guardado en crudo y
  con `UNIQUE(provider, provider_event_id)` para que **repetir un webhook no
  vuelva a aplicar el efecto** (idempotencia).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.base import TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class PaymentStatus(enum.StrEnum):
    """Estado del intento de pago."""

    PENDING = "pending"  # creado, esperando que el comprador pague
    PROCESSING = "processing"  # el proveedor lo está procesando
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Intento de pago de una orden."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", "idempotency_key", name="uq_payment_idempotency"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_reference: Mapped[str] = mapped_column(
        String(120), unique=True, index=True, nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_attempt_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    checkout_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Webhook recibido del proveedor (idempotente por `provider_event_id`)."""

    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_payment_event"),)

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
